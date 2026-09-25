# AgentKit — AI Agent Builder (WhatsApp e Instagram)

Construye tu propio agente de IA para WhatsApp o Instagram en menos de 30 minutos.
No necesitas saber programar. Claude Code te entrevista y configura todo por ti.

---

## Qué es AgentKit?

AgentKit tiene dos partes:

1. **Un core compartido** (el paquete Python `agentkit/` de este repo) con todo el
   código real del agente: servidor, cerebro con Claude, memoria, proveedores de
   WhatsApp, herramientas, humanización, voz, pagos y reportes.
2. **Un flujo guiado con Claude Code** (`CLAUDE.md`) que te entrevista sobre tu
   negocio y genera la capa fina de tu agente: configuración, conocimiento y
   herramientas propias.

Cada agente es una carpeta pequeña que instala el core como dependencia.
Cuando el core mejora, **todos tus agentes mejoran** con un `pip install --upgrade`.

## Qué sabe hacer un agente de AgentKit?

- Responder preguntas frecuentes usando los archivos de tu negocio (`/knowledge`)
- **Ejecutar herramientas solo** (tool use): registrar leads, crear tickets de
  soporte, consultar el catálogo — y notificar a tu equipo por WhatsApp
- **Recordar a cada cliente** entre conversaciones (nombre, compras, intereses)
- **Derivar a un humano** cuando el cliente quiere cerrar la compra: pausa el bot
  y le pasa el contexto completo a tu asesor
- **Cobrar dentro del chat** con links de pago — eliges tu pasarela según tu país:
  Wompi (Colombia), MercadoPago (LatAm) o Stripe (global)
- Atender por **WhatsApp** (Meta Cloud API o Twilio) o por **Instagram DM**
- Responder en **burbujas cortas con pausas**, como escribe una persona
- Entender **notas de voz** y responder con **voz natural** (opcional; ver "Voz del agente")
- Enviar un **reporte diario** al equipo: leads, tickets y conversaciones
- Validar la **firma de los webhooks** (Meta y Twilio) — nadie puede inyectar mensajes falsos

## Cómo empezar

```bash
git clone https://github.com/NicoCardona1106/agentkit.git
cd agentkit
bash start.sh   # verifica Python 3.11+ y Claude Code

claude
# Dentro de Claude Code escribe:
/build-agent
```

Claude Code te hace ~12 preguntas sobre tu negocio (nombre, tono, horario,
credenciales de WhatsApp…) y genera tu agente en su propia carpeta dentro de
`agentes/` — puedes crear todos los agentes que quieras desde el mismo clon,
el repo nunca se ensucia:

```
agentes/mi-agente/
├── config/business.yaml    ← datos del negocio
├── config/prompts.yaml     ← personalidad del agente
├── knowledge/              ← tu menú, precios, FAQ
├── tools.py                ← (opcional) herramientas propias
├── requirements.txt        ← instala el core agentkit
├── Dockerfile / docker-compose.yml / .env
```

## Probar y desplegar

```bash
python -m agentkit.chat                          # chatea con tu agente en la terminal
uvicorn agentkit.main:app --reload --port 8000   # servidor local
```

Producción: sube la carpeta del agente a GitHub y despliégala en Railway
(Claude Code te guía paso a paso, incluido PostgreSQL para memoria permanente
y la configuración del webhook en Meta o Twilio).

## Endpoints para monitoreo

- `GET /reporte?token=<REPORTE_TOKEN>` — genera y envía el reporte diario
  (leads, tickets, conversaciones) al equipo por WhatsApp.
- `GET /estado?token=<REPORTE_TOKEN>` — estado del agente en JSON para un
  panel externo (versión, proveedor, modelo, uptime, modo borrador, cifras
  de las últimas 24h, tickets abiertos, borradores pendientes, errores y
  `costo_usd`: gasto en APIs de hoy y del mes en hora de Bogotá, con desglose
  del mes en `llm`/`stt`/`tts`, montos como texto decimal, p. ej. `"0.012345"`,
  y `modelos_sin_precio`: modelos usados este mes que se registraron con costo 0
  porque no tienen precio en la tabla — el panel debe marcarlos. Si el cálculo
  del costo falla, `costo_usd` llega en `null` y el resto del estado sale igual).
  Nunca expone teléfonos ni el contenido de los mensajes. Recomendado para
  paneles: manda el token por cabecera `X-Reporte-Token` en vez de `?token=`,
  así no queda en los access logs.

Ambos comparten `REPORTE_TOKEN`: sin token o con uno incorrecto, 403.

Cada llamada a Claude, a la transcripción y a la voz queda en la tabla
`uso_api` con su costo en USD (precios en `agentkit/precios.py`; para
corregir uno sin tocar código, crea `config/precios.json`, p. ej.
`{"claude-haiku-4-5": {"salida": "5"}}`, o apunta `PRECIOS_ARCHIVO` a otro JSON;
si el JSON está mal formado se registra el error en el log y se usa la tabla interna).

**El costo de la voz de salida es estimado**, no exacto: la duración del audio
se estima por caracteres (~15 por segundo). El precio de Gemini 2.5 Flash TTS
sí está verificado (USD 10 por millón de tokens de audio, 25 tokens/s ≈ USD
0,015/min); el de `gpt-4o-mini-tts` (respaldo, USD 0,015/min) no — OpenAI hoy
lo publica solo por tokens de audio.
El de Claude sí sale del `usage` real, y el de la transcripción de la duración
real de la nota de voz (OGG de WhatsApp; otros formatos se estiman por tamaño).

## Voz del agente (sin tocar código)

Decisión tras la prueba de oído (2026-09-25): el agente **escucha** con OpenAI
`gpt-4o-mini-transcribe` y **habla** con Gemini `gemini-2.5-flash-preview-tts`,
voz `Kore`. OpenAI `gpt-4o-mini-tts` (voz `marin`) queda de respaldo si no hay
`GEMINI_API_KEY`.

> **Advertencia (Ley 1581):** usa una `GEMINI_API_KEY` de un proyecto con
> **facturación activa** (tier de pago). En el tier gratis Google puede usar los
> datos para entrenar sus modelos, y eso choca con el tratamiento de datos que
> AgentKit promete al cliente.

Todo se cambia en el `.env` y se aplica al reiniciar el agente:

| Variable | Default | Para qué |
|----------|---------|----------|
| `GEMINI_API_KEY` | — | Voz de salida (Gemini, requiere `ffmpeg` instalado para pasar a mp3). Key con facturación activa |
| `OPENAI_API_KEY` | — | Entiende notas de voz (`gpt-4o-mini-transcribe`) y es el respaldo de la voz de salida (`gpt-4o-mini-tts`, mp3) |
| `TTS_PROVEEDOR` | `gemini` | `openai` para forzar el respaldo |
| `TTS_VOZ` | `Kore` (Gemini) / `marin` (OpenAI) | Voz de salida. Gemini: `Kore`, `Puck`, `Zephyr`, `Aoede`… (30 voces). OpenAI: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`, `marin`, `cedar` |
| `GEMINI_TTS_VOZ` / `OPENAI_TTS_VOZ` | — | Voz solo para ese proveedor; gana sobre `TTS_VOZ` (útil para dejar lista la voz del respaldo) |
| `TTS_INSTRUCCIONES` | español de Colombia, cálido y conversacional, ritmo natural, nada de locutor ni robot | Cómo habla: tono, acento, ritmo. Texto libre, p. ej. `TTS_INSTRUCCIONES="Habla como una recepcionista paisa, alegre y sin afanes"`. OpenAI la recibe en su campo `instructions`; Gemini no tiene ese campo y la recibe **antepuesta al texto**: `instrucciones`, una línea en blanco y el texto (así se generó la muestra elegida, sin que el modelo la leyera en voz alta) |
| `TTS_MODELO` | `gemini-2.5-flash-preview-tts` (Gemini) / `gpt-4o-mini-tts` (OpenAI) | Modelo de voz de salida. `gemini-3.8-flash-tts` es el sucesor si el preview se retira, pero lee el texto literal (leería las instrucciones) y devuelve WAV: no cambiarlo sin adaptar el core y repetir la prueba de oído |
| `STT_PROVEEDOR` | `openai` | `groq` para transcribir gratis con `GROQ_API_KEY` |
| `VOZ_MODELO` | `gpt-4o-mini-transcribe` (OpenAI) / `whisper-large-v3` (Groq) | Modelo de transcripción |

Para que responda en voz también hace falta `PUBLIC_URL` (el proveedor
descarga el audio desde `/audio/{id}`). Si el cliente escribe, el agente
responde por texto; si manda nota de voz, responde con nota de voz.

- Cada proveedor valida el modelo y la voz que recibe: si el valor es de otro
  proveedor (p. ej. `TTS_VOZ=marin` cuando habla Gemini), lo ignora, usa su
  default y lo avisa una vez en el log.
- Forzar un proveedor (`TTS_PROVEEDOR` / `STT_PROVEEDOR`) sin su key deja al
  agente **sin esa voz**: no cae al otro proveedor.

### Actualizar un agente a v0.7.0

El modelo por defecto pasa a Haiku 4.5, la transcripción a OpenAI y la voz de
salida a Gemini `Kore`. En el `.env` del agente:

- **Agregar** `OPENAI_API_KEY` (escuchar) y `GEMINI_API_KEY` con facturación
  activa (hablar); el contenedor necesita `ffmpeg` (el Dockerfile de AgentKit ya
  lo instala).
- **Borrar** `VOZ_MODELO=whisper-large-v3` (salvo que siga en Groq),
  `TTS_VOZ=nova`/`marin`, `TTS_MODELO=gpt-4o-mini-tts` y
  `CLAUDE_MODEL=claude-sonnet-5` (salvo que ese agente necesite Sonnet). Si se
  quedan no rompen nada — se ignoran con un aviso o se vuelven el respaldo —,
  pero confunden. `GROQ_API_KEY` puede quedarse como respaldo.

## Stack

| Componente | Tecnología |
|-----------|-----------|
| Runtime | Python 3.11+ |
| Servidor | FastAPI + Uvicorn |
| IA | Anthropic Claude (`claude-haiku-4-5` por defecto, con tool use; `CLAUDE_MODEL` para cambiarlo) |
| Canales | WhatsApp (Meta Cloud API / Twilio) e Instagram DM |
| Base de datos | SQLite (local) / PostgreSQL (producción) |
| Voz | Escucha: OpenAI `gpt-4o-mini-transcribe`. Habla: Gemini `gemini-2.5-flash-preview-tts` voz `Kore` (OpenAI de respaldo). Opcional |
| Pagos | Wompi / MercadoPago / Stripe (opcional, según país) |
| Deploy | Docker + Railway |

## Desarrollo del core

```bash
python tests/test_core.py   # self-checks sin red ni API keys
```

---

Licencia: ver `LICENSE`.
