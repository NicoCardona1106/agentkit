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

**La voz de salida por defecto (`gpt-audio-1.5`) se cobra exacta:** cada
respuesta trae su `usage` (tokens de texto de entrada, texto y audio de salida)
y se registra con los precios verificados el 2026-09-25 (texto USD 2,50/10,00
por millón, audio USD 32/64 por millón). Si la guarda de fidelidad descarta el
audio, esa llamada también queda registrada, además de la del respaldo.
**El costo de los respaldos es estimado**: la duración del audio se estima por
caracteres (~15 por segundo). El precio de Gemini 2.5 Flash TTS sí está
verificado (USD 10 por millón de tokens de audio, 25 tokens/s ≈ USD 0,015/min);
el de `gpt-4o-mini-tts` (USD 0,015/min) no — OpenAI hoy lo publica solo por
tokens de audio.
El de Claude sí sale del `usage` real, y el de la transcripción de la duración
real de la nota de voz (OGG de WhatsApp; otros formatos se estiman por tamaño).

## Voz del agente (sin tocar código)

Decisión de Nicolas tras la prueba de oído a ciegas (2026-09-25, muestra «O3»):
el agente **escucha** con OpenAI `gpt-4o-mini-transcribe` y **habla** con el
modelo conversacional `gpt-audio-1.5`, voz `marin` (femenina), por Chat
Completions con audio. Fue la voz más humana de la prueba; la regla es que se
sienta humano en todo momento, calidad antes que precio.

- **Costo:** ~USD 0,08 por minuto de voz (~USD 9 por cliente al mes a 500
  respuestas en voz). Es ~5 veces el TTS barato: tenerlo en cuenta al cotizar.
- **Guarda de fidelidad:** `gpt-audio` es conversacional y puede cambiar el
  texto (en la prueba, la variante mini se inventó respuestas). El core compara
  la **transcripción que devuelve el propio modelo** con lo que debía decir (no
  reconoce el mp3: si el audio se apartara de esa transcripción, no lo vería),
  sin mirar puntuación, tildes ni `$`, y unificando miles (`30.000`, `30,000`,
  `30 000`) y `a. m.`/`p. m.`. Los números (precio, placa, hora) y las palabras
  críticas (`no`, `sí`, `nunca`, `ni`, `sin`, `tampoco`, `jamás`, `hoy`,
  `mañana`, `ayer` y los días de la semana) deben coincidir exactos y en orden;
  el resto, con similitud ≥ 0,9 (≥ 0,95 desde 20 palabras). Si no, descarta ese
  audio y usa el respaldo. Límite: un sustantivo cambiado en un texto largo
  (carro → moto) puede pasar.
- **Respaldo automático:** si `gpt-audio` falla o no pasa la guarda, habla
  `gpt-4o-mini-tts` (voz `marin`, misma `OPENAI_API_KEY`) y, si también falla,
  Gemini `gemini-2.5-flash-preview-tts` voz `Kore` (si hay `GEMINI_API_KEY`).
  Si todo falla, o si la voz no está lista en `VOZ_TIMEOUT_TOTAL` segundos
  (default 45; cada llamada tiene además su propio timeout), la respuesta sale
  en texto.
- **Voz femenina:** el personaje del agente debe ser femenino (nombre y forma
  de hablar), para que la voz y el texto no se contradigan.
- **Texto fluido:** cuando el cliente manda nota de voz, el cerebro recibe una
  instrucción extra para ese turno: escribir de corrido, con pocas comas.

> **Advertencia (Ley 1581):** si usas el respaldo Gemini, usa una `GEMINI_API_KEY` de un proyecto con
> **facturación activa** (tier de pago). En el tier gratis Google puede usar los
> datos para entrenar sus modelos, y eso choca con el tratamiento de datos que
> AgentKit promete al cliente.

Todo se cambia en el `.env` y se aplica al reiniciar el agente:

| Variable | Default | Para qué |
|----------|---------|----------|
| `OPENAI_API_KEY` | — | Entiende notas de voz (`gpt-4o-mini-transcribe`) y habla (`gpt-audio-1.5` y su respaldo `gpt-4o-mini-tts`) |
| `GEMINI_API_KEY` | — | Último respaldo de la voz de salida (Gemini, requiere `ffmpeg` instalado para pasar a mp3). Key con facturación activa |
| `TTS_PROVEEDOR` | `openai-audio` | Proveedor principal: `openai-audio` (`gpt-audio-1.5`), `openai` (`gpt-4o-mini-tts`) o `gemini`. Si falla, siguen los respaldos `openai` y `gemini` que tengan key (`gpt-audio` nunca es respaldo: forzar otro sirve para no pagarlo) |
| `OPENAI_AUDIO_MODELO` | `gpt-audio-1.5` | Modelo conversacional de voz; solo acepta `gpt-audio*` (gana sobre `TTS_MODELO`) |
| `TTS_VOZ` | `marin` (OpenAI) / `Kore` (Gemini) | Voz de salida. `gpt-audio` y `gpt-4o-mini-tts` aceptan las mismas: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`, `verse`, `marin`, `cedar` (verificado con llamadas reales el 2026-09-25) |
| `VOZ_TIMEOUT_TOTAL` | `45` | Segundos máximos para tener la nota de voz (principal + respaldos); si vence, la respuesta sale en texto |
| `GEMINI_TTS_VOZ` / `OPENAI_TTS_VOZ` | — | Voz solo para ese proveedor (`OPENAI_TTS_VOZ` vale para `gpt-audio` y `gpt-4o-mini-tts`); gana sobre `TTS_VOZ` |
| `TTS_INSTRUCCIONES` | OpenAI: el estilo «fluido» de la muestra O3 (español de Colombia, cálido y cercano, de corrido, sin pausas largas, nada de locutor ni robot). Gemini: el estilo de su muestra Kore | Cómo habla: tono, acento, ritmo. Texto libre, p. ej. `TTS_INSTRUCCIONES="Habla como una recepcionista paisa, alegre y sin afanes"`. `gpt-audio` la recibe en el mensaje system seguida de una cláusula fija («di palabra por palabra el mensaje del usuario, no agregues ni quites nada»); `gpt-4o-mini-tts` en su campo `instructions`; Gemini no tiene ese campo y la recibe **antepuesta al texto**: `instrucciones`, una línea en blanco y el texto |
| `TTS_MODELO` | `gpt-audio-1.5` / `gpt-4o-mini-tts` / `gemini-2.5-flash-preview-tts` | Modelo de voz de salida; cada proveedor ignora el que no es suyo. `gemini-3.8-flash-tts` es el sucesor si el preview se retira, pero lee el texto literal (leería las instrucciones) y devuelve WAV: no cambiarlo sin adaptar el core y repetir la prueba de oído |
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

### Actualizar un agente a v0.7.1

La voz de salida pasa a `gpt-audio-1.5` voz `marin` con solo tener
`OPENAI_API_KEY`; Gemini queda de último respaldo. En el `.env` del agente:

- **Borrar** `TTS_PROVEEDOR=gemini`, `TTS_VOZ=Kore` y `TTS_MODELO=...` si
  están (el `Kore` se puede dejar en `GEMINI_TTS_VOZ`) y `TTS_INSTRUCCIONES`
  salvo que sea un estilo propio del negocio.
- Revisar que el personaje del agente (`config/prompts.yaml`) sea **femenino**.
- Recalcular la mensualidad con ~USD 0,08 por minuto de voz.

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
| Voz | Escucha: OpenAI `gpt-4o-mini-transcribe`. Habla: OpenAI `gpt-audio-1.5` voz `marin` (respaldos `gpt-4o-mini-tts` y Gemini `Kore`). Opcional |
| Pagos | Wompi / MercadoPago / Stripe (opcional, según país) |
| Deploy | Docker + Railway |

## Desarrollo del core

```bash
python tests/test_core.py   # self-checks sin red ni API keys
```

---

Licencia: ver `LICENSE`.
