# agentkit/web.py — Canal de chat web: el MISMO agente (memoria, herramientas, leads y
# avisos a ADMIN_PHONE) que atiende WhatsApp, embebido en una landing con /widget.js.
#
# Se activa con WEB_CHAT_ORIGINS (orígenes separados por coma) en el .env. Sin esa
# variable, /chat y /widget.js responden 404: el canal está apagado por defecto.

import logging
import os
import time
import uuid
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from agentkit import brain, humanizar, memory

logger = logging.getLogger("agentkit")
router = APIRouter()

MAX_TEXTO = 1000
MAX_ORIGEN = 200

# ponytail: límites en memoria, por proceso (se reinician al reiniciar el agente) — alcanza
# para un solo worker; si el agente corre con varios procesos, pasar a un store compartido
# (Redis) para que el tope sea global.
_ip_ventana: dict[str, deque[float]] = defaultdict(deque)
_sesion_conteo: dict[str, int] = defaultdict(int)


def _origenes_permitidos() -> set[str]:
    return {o.strip() for o in os.getenv("WEB_CHAT_ORIGINS", "").split(",") if o.strip()}


def _canal_activo() -> bool:
    return bool(_origenes_permitidos())


def _proveedor():
    """El mismo proveedor de WhatsApp que usa /webhook (importado tarde: evita el ciclo
    main <-> web, y agentkit.main ya está totalmente cargado quando llega la request)."""
    from agentkit import main as main_mod
    return main_mod.proveedor


def _limite_ip(ip: str) -> bool:
    """True si la IP puede mandar otro mensaje (ventana móvil de 1h, WEB_CHAT_MAX_IP_HORA)."""
    tope = int(os.getenv("WEB_CHAT_MAX_IP_HORA", "30"))
    ahora = time.monotonic()
    ventana = _ip_ventana[ip]
    while ventana and ahora - ventana[0] > 3600:
        ventana.popleft()
    if len(ventana) >= tope:
        return False
    ventana.append(ahora)
    return True


def _limite_sesion(sesion: str) -> bool:
    """True si la sesión puede mandar otro mensaje (tope total, WEB_CHAT_MAX_SESION)."""
    tope = int(os.getenv("WEB_CHAT_MAX_SESION", "40"))
    if _sesion_conteo[sesion] >= tope:
        return False
    _sesion_conteo[sesion] += 1
    return True


@router.options("/chat")
async def chat_preflight(request: Request):
    """Preflight CORS: un POST con Content-Type: application/json no es una request "simple"
    y el navegador la manda antes del POST real."""
    if not _canal_activo():
        raise HTTPException(status_code=404)
    origen = request.headers.get("origin", "")
    if origen not in _origenes_permitidos():
        raise HTTPException(status_code=400, detail="Origen no permitido")
    return Response(status_code=204, headers={
        "Access-Control-Allow-Origin": origen,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    })


@router.post("/chat")
async def chat(request: Request, response: Response):
    if not _canal_activo():
        raise HTTPException(status_code=404)

    origin = request.headers.get("origin")
    if origin:
        if origin not in _origenes_permitidos():
            raise HTTPException(status_code=403, detail="Origen no permitido")
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"

    try:
        cuerpo = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    sesion = str(cuerpo.get("sesion") or "")
    texto = str(cuerpo.get("texto") or "")
    origen_pagina = str(cuerpo.get("origen") or "")[:MAX_ORIGEN]

    try:
        uuid.UUID(sesion)
    except ValueError:
        raise HTTPException(status_code=400, detail="sesion inválida: debe ser un UUID")
    if not (1 <= len(texto) <= MAX_TEXTO):
        raise HTTPException(status_code=400, detail="texto debe tener entre 1 y 1000 caracteres")

    ip = request.client.host if request.client else "desconocida"
    if not _limite_ip(ip):
        raise HTTPException(status_code=429, detail="Demasiados mensajes desde tu red — intenta en un rato")
    if not _limite_sesion(sesion):
        raise HTTPException(status_code=429, detail="Se alcanzó el máximo de mensajes de esta conversación")

    telefono = f"web:{sesion}"

    if await memory.conversacion_pausada(telefono):
        await memory.guardar_mensaje(telefono, "user", texto)
        return {"respuestas": [_msg_pausa()]}

    tope = _d(os.getenv("WEB_CHAT_TOPE_USD_DIA", "3"))
    if await memory.costo_web_hoy() >= tope:
        logger.warning("Chat web: tope de costo diario alcanzado, /chat responde 503")
        return JSONResponse(status_code=503, content={"respuestas": [_msg_tope()]})

    # Sin voz, sin modo borrador en web: la respuesta sale directo aunque MODO_BORRADOR
    # esté activo (ver contrato de este canal) — no pasa por agentkit.borrador.
    historial = await memory.obtener_historial(telefono)
    respuesta = await brain.generar_respuesta(telefono, texto, historial, _proveedor(),
                                              en_voz=False, origen=origen_pagina)

    await memory.guardar_mensaje(telefono, "user", texto)
    await memory.guardar_mensaje(telefono, "assistant", respuesta)

    return {"respuestas": humanizar.partir_en_burbujas(respuesta)}


def _msg_pausa() -> str:
    return os.getenv("WEB_CHAT_MSG_PAUSA", "Ya le avisé a un asesor; te escribe pronto por WhatsApp.")


def _msg_tope() -> str:
    return os.getenv("WEB_CHAT_MSG_TOPE", "Por hoy ya no puedo seguir esta conversación. Escríbenos por WhatsApp.")


def _d(valor: str) -> Decimal:
    try:
        return Decimal(valor)
    except InvalidOperation:
        return Decimal("3")  # valor inválido en el .env: cae al default del contrato


@router.get("/widget.js")
async def widget_js():
    if not _canal_activo():
        raise HTTPException(status_code=404)
    return Response(content=_WIDGET_JS, media_type="application/javascript; charset=utf-8")


# Script embebible sin dependencias (JS + CSS inline). Toma los colores de la página
# (var(--bg), var(--text), var(--navy), var(--on-navy), var(--shd), var(--shl)) con
# fallbacks propios; hereda data-theme="dark" sin código extra porque son custom properties.
_WIDGET_JS = r"""(function(){
"use strict";
var script = document.currentScript;
if (!script) return;
var base = script.src.replace(/\/widget\.js.*$/, "");
var titulo = script.getAttribute("data-titulo") || "este sitio";
var saludo = script.getAttribute("data-saludo") || "";
var fallbackTexto = script.getAttribute("data-fallback") || "No pude conectarme. Intenta más tarde.";
var whatsapp = script.getAttribute("data-whatsapp") || "";

function uuid() {
  try { return crypto.randomUUID(); } catch (e) {
    // ponytail: navegador sin randomUUID — v4 aproximado, alcanza para un id de sesión de chat
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }
}

function sesionId() {
  try {
    var s = sessionStorage.getItem("agentkit_sesion");
    if (!s) { s = uuid(); sessionStorage.setItem("agentkit_sesion", s); }
    return s;
  } catch (e) { return uuid(); }
}

var sesion = sesionId();
var origen = (location.pathname + location.search).slice(0, 200);

var css =
  "#agentkit-btn{position:fixed;bottom:20px;right:20px;width:56px;height:56px;min-width:44px;" +
  "min-height:44px;border-radius:50%;border:none;cursor:pointer;font-size:24px;z-index:999999;" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff);box-shadow:var(--shd,0 2px 10px rgba(0,0,0,.3))}" +
  "#agentkit-panel{position:fixed;bottom:86px;right:20px;width:min(340px,90vw);max-height:70vh;" +
  "border-radius:12px;z-index:999999;overflow:hidden;font:14px/1.4 system-ui,sans-serif;display:none;" +
  "flex-direction:column;background:var(--bg,#fff);color:var(--text,#111);" +
  "box-shadow:var(--shl,0 4px 24px rgba(0,0,0,.2))}" +
  "#agentkit-panel.abierto{display:flex}" +
  "#agentkit-header{padding:12px;display:flex;justify-content:space-between;align-items:center;" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "#agentkit-cerrar{background:none;border:none;color:inherit;font-size:20px;cursor:pointer;" +
  "min-width:44px;min-height:44px}" +
  "#agentkit-mensajes{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}" +
  ".agentkit-burbuja{padding:8px 12px;border-radius:10px;max-width:85%;word-wrap:break-word}" +
  ".agentkit-burbuja.bot{align-self:flex-start;background:var(--shl,#f0f0f0)}" +
  ".agentkit-burbuja.yo{align-self:flex-end;background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "#agentkit-panel a{color:inherit}" +
  "#agentkit-form{display:flex;gap:8px;padding:8px;border-top:1px solid var(--shd,#ddd)}" +
  "#agentkit-input{flex:1;min-height:44px;border-radius:8px;padding:8px;border:1px solid var(--shd,#ccc);" +
  "background:var(--bg,#fff);color:var(--text,#111)}" +
  "#agentkit-enviar{min-width:44px;min-height:44px;border:none;border-radius:8px;cursor:pointer;" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "@media (prefers-reduced-motion:no-preference){#agentkit-panel{transition:opacity .15s ease}}";
var estilo = document.createElement("style");
estilo.textContent = css;
document.head.appendChild(estilo);

var btn = document.createElement("button");
btn.id = "agentkit-btn";
btn.type = "button";
btn.setAttribute("aria-label", "Abrir chat");
btn.textContent = "💬";

var panel = document.createElement("div");
panel.id = "agentkit-panel";
panel.setAttribute("role", "dialog");
panel.setAttribute("aria-modal", "true");
panel.setAttribute("aria-label", titulo);
panel.innerHTML =
  '<div id="agentkit-header"><strong></strong>' +
  '<button id="agentkit-cerrar" type="button" aria-label="Cerrar chat">✕</button></div>' +
  '<div id="agentkit-mensajes" role="log" aria-live="polite"></div>' +
  '<form id="agentkit-form">' +
  '<input id="agentkit-input" type="text" maxlength="1000" autocomplete="off" aria-label="Escribe tu mensaje"/>' +
  '<button id="agentkit-enviar" type="submit" aria-label="Enviar">➤</button>' +
  '</form>';
panel.querySelector("#agentkit-header strong").textContent = titulo;

document.body.appendChild(btn);
document.body.appendChild(panel);

var mensajes = panel.querySelector("#agentkit-mensajes");
var input = panel.querySelector("#agentkit-input");
var form = panel.querySelector("#agentkit-form");
var cerrarBtn = panel.querySelector("#agentkit-cerrar");

function burbuja(texto, clase) {
  var d = document.createElement("div");
  d.className = "agentkit-burbuja " + clase;
  d.textContent = texto;
  mensajes.appendChild(d);
  mensajes.scrollTop = mensajes.scrollHeight;
  return d;
}

var saludado = false;
function abrir() {
  panel.classList.add("abierto");
  if (!saludado) {
    burbuja("Hola, soy un asistente con IA de " + titulo + "." + (saludo ? " " + saludo : ""), "bot");
    saludado = true;
  }
  input.focus();
  document.addEventListener("keydown", alCerrarConEsc);
  // ponytail: trampa de foco simple (refoca si sale del panel) en vez de ciclar Tab/Shift+Tab
  // entre los 3 elementos enfocables; sube a un ciclo explícito si se agregan más controles
  document.addEventListener("focusin", atraparFoco);
}

function cerrar() {
  panel.classList.remove("abierto");
  document.removeEventListener("keydown", alCerrarConEsc);
  document.removeEventListener("focusin", atraparFoco);
  btn.focus();
}

function alCerrarConEsc(e) {
  if (e.key === "Escape") cerrar();
}

function atraparFoco(e) {
  if (panel.classList.contains("abierto") && !panel.contains(e.target)) input.focus();
}

btn.addEventListener("click", function () {
  if (panel.classList.contains("abierto")) cerrar(); else abrir();
});
cerrarBtn.addEventListener("click", cerrar);

form.addEventListener("submit", function (e) {
  e.preventDefault();
  var texto = input.value.trim();
  if (!texto) return;
  input.value = "";
  burbuja(texto, "yo");
  enviar(texto);
});

function enviar(texto) {
  fetch(base + "/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sesion: sesion, texto: texto, origen: origen })
  }).then(function (r) {
    if (!r.ok) throw new Error("http " + r.status);
    return r.json();
  }).then(function (data) {
    (data.respuestas || []).forEach(function (b) { burbuja(b, "bot"); });
  }).catch(function () {
    burbuja(fallbackTexto, "bot");
    if (whatsapp) {
      var a = document.createElement("a");
      a.href = "https://wa.me/" + whatsapp;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Escríbenos por WhatsApp";
      mensajes.appendChild(a);
    }
  });
}

window.AgentKitChat = { open: abrir };
})();
"""
