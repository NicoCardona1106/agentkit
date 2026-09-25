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
  del mes en `llm`/`stt`/`tts`; montos como texto decimal, p. ej. `"0.012345"`).
  Nunca expone teléfonos ni el contenido de los mensajes. Recomendado para
  paneles: manda el token por cabecera `X-Reporte-Token` en vez de `?token=`,
  así no queda en los access logs.

Ambos comparten `REPORTE_TOKEN`: sin token o con uno incorrecto, 403.

Cada llamada a Claude, a la transcripción y a la voz queda en la tabla
`uso_api` con su costo en USD (precios en `agentkit/precios.py`; para
corregir uno sin tocar código, crea `config/precios.json`, p. ej.
`{"claude-haiku-4-5": {"salida": "5"}}`, o apunta `PRECIOS_ARCHIVO` a otro JSON).

## Voz del agente (sin tocar código)

Todo se cambia en el `.env` y se aplica al reiniciar el agente:

| Variable | Default | Para qué |
|----------|---------|----------|
| `OPENAI_API_KEY` | — | Activa la voz: entiende notas de voz (`gpt-4o-mini-transcribe`) y responde en voz (`gpt-4o-mini-tts`, mp3) |
| `TTS_VOZ` | `marin` | Voz de salida. Válidas: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`, `marin`, `cedar` (en prueba de oído: `marin`, `coral`, `cedar`) |
| `TTS_INSTRUCCIONES` | español de Colombia, cálido y conversacional, ritmo natural, nada de locutor ni robot | Cómo habla: tono, acento, ritmo. Texto libre, p. ej. `TTS_INSTRUCCIONES="Habla como una recepcionista paisa, alegre y sin afanes"` |
| `TTS_PROVEEDOR` | `openai` | `gemini` solo como respaldo (`GEMINI_API_KEY`, requiere ffmpeg) |
| `STT_PROVEEDOR` | `openai` | `groq` para transcribir gratis con `GROQ_API_KEY` |

Para que responda en voz también hace falta `PUBLIC_URL` (el proveedor
descarga el audio desde `/audio/{id}`). Si el cliente escribe, el agente
responde por texto; si manda nota de voz, responde con nota de voz.

## Stack

| Componente | Tecnología |
|-----------|-----------|
| Runtime | Python 3.11+ |
| Servidor | FastAPI + Uvicorn |
| IA | Anthropic Claude (`claude-haiku-4-5` por defecto, con tool use; `CLAUDE_MODEL` para cambiarlo) |
| Canales | WhatsApp (Meta Cloud API / Twilio) e Instagram DM |
| Base de datos | SQLite (local) / PostgreSQL (producción) |
| Voz | OpenAI `gpt-4o-mini-transcribe` + `gpt-4o-mini-tts` (opcional; Groq/Gemini de respaldo) |
| Pagos | Wompi / MercadoPago / Stripe (opcional, según país) |
| Deploy | Docker + Railway |

## Desarrollo del core

```bash
python tests/test_core.py   # self-checks sin red ni API keys
```

---

Licencia: ver `LICENSE`.
