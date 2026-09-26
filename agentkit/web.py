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


# Script embebible sin dependencias (JS + CSS inline). Acabado neumórfico (sombras dobles
# en relieve/hundido) con los colores de la página (var(--bg), var(--text), var(--navy),
# var(--on-navy), var(--shd), var(--shl)) y var(--f-body) para la tipografía; todos con
# fallbacks propios. Hereda data-theme="dark" sin código extra porque son custom properties.
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

// Sombras dobles del acabado neumórfico (colores de la página; fallbacks neutros si no
// los define). shd = sombra oscura (abajo-derecha), shl = luz clara (arriba-izquierda).
var shd = "var(--shd,rgba(0,0,0,.16))";
var shl = "var(--shl,rgba(255,255,255,.75))";
var raise = "6px 6px 13px " + shd + ",-6px -6px 13px " + shl;
var raiseSm = "3px 3px 7px " + shd + ",-3px -3px 7px " + shl;
var inset = "inset 4px 4px 9px " + shd + ",inset -4px -4px 9px " + shl;

var css =
  "#agentkit-btn{position:fixed;bottom:20px;right:20px;width:56px;height:56px;min-width:44px;" +
  "min-height:44px;border-radius:50%;border:none;cursor:pointer;z-index:999999;display:grid;" +
  "place-items:center;background:var(--navy,#1a2b4c);color:var(--on-navy,#fff);box-shadow:" + raise + "}" +
  "#agentkit-btn svg{width:24px;height:24px}" +
  "#agentkit-panel{position:fixed;bottom:86px;right:20px;width:min(340px,90vw);max-height:70vh;" +
  "border-radius:24px;z-index:999999;overflow:hidden;font-size:14px;line-height:1.4;" +
  "font-family:var(--f-body,inherit);display:none;" +
  "flex-direction:column;background:var(--bg,#fff);color:var(--text,#111);box-shadow:" + raise + "}" +
  "#agentkit-panel.abierto{display:flex}" +
  "#agentkit-header{padding:12px 14px;display:flex;justify-content:space-between;align-items:center;" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "#agentkit-cerrar{background:none;border:none;color:inherit;font-size:18px;cursor:pointer;" +
  "width:44px;height:44px;border-radius:50%;display:grid;place-items:center}" +
  "#agentkit-mensajes{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}" +
  ".agentkit-burbuja{padding:9px 13px;border-radius:18px;max-width:85%;word-wrap:break-word}" +
  ".agentkit-burbuja.bot{align-self:flex-start;border-bottom-left-radius:6px;box-shadow:" + raiseSm + "}" +
  ".agentkit-burbuja.yo{align-self:flex-end;border-bottom-right-radius:6px;box-shadow:" + raiseSm + ";" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "#agentkit-panel a{color:inherit}" +
  "#agentkit-form{display:flex;gap:8px;padding:10px 12px 12px}" +
  "#agentkit-input{flex:1;height:44px;border-radius:14px;padding:0 14px;border:none;" +
  "background:var(--bg,#fff);color:var(--text,#111);box-shadow:" + inset + "}" +
  "#agentkit-enviar{width:44px;height:44px;min-width:44px;min-height:44px;border:none;" +
  "border-radius:50%;cursor:pointer;display:grid;place-items:center;" +
  "background:var(--navy,#1a2b4c);color:var(--on-navy,#fff)}" +
  "#agentkit-enviar svg{width:18px;height:18px}" +
  "#agentkit-panel :focus-visible,#agentkit-btn:focus-visible{outline:2px solid var(--focus,#07726A);outline-offset:2px}" +
  "@media (prefers-reduced-motion:no-preference){#agentkit-panel{transition:opacity .15s ease}}";
var estilo = document.createElement("style");
estilo.textContent = css;
document.head.appendChild(estilo);

var btn = document.createElement("button");
btn.id = "agentkit-btn";
btn.type = "button";
btn.setAttribute("aria-label", "Abrir chat");
btn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
  '<path d="M4 4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3v3.5L11.5 18H20a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H4z"/></svg>';

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
  '<button id="agentkit-enviar" type="submit" aria-label="Enviar">' +
  '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
  '<path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>' +
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
