# AgentKit v0.1.0 — De generador de código a core compartido

**Bitácora — 2 de agosto de 2026**

## Qué cambió y por qué

Antes, AgentKit era un `CLAUDE.md` gigante con templates: Claude Code regeneraba
todo el código para cada agente nuevo. Problema: cada agente nacía como copia y
divergía — las mejoras al kit no llegaban a los agentes ya creados (ej: Ragnar).

Ahora AgentKit es un **paquete Python real** (`agentkit/`). Cada agente es solo
una capa fina: `config/` + `knowledge/` + `tools.py` opcional + `.env`, con
`requirements.txt` apuntando a este repo. Mejorar el core = mejorar todos los
agentes con `pip install --upgrade`.

## Qué trae el core v0.1.0 (visión de la bitácora de Ragnar, etapas 1–5)

**Etapa 1 — Cimientos**
- PostgreSQL en producción via `DATABASE_URL` (SQLite en local)
- Validación de firma de webhooks: Meta (`X-Hub-Signature-256` + `META_APP_SECRET`)
  y Twilio (`X-Twilio-Signature` + `PUBLIC_URL`)
- Dedup de webhooks reenviados + procesamiento en background (evita duplicados
  cuando Claude tarda más que el timeout del webhook)

**Etapa 2 — Tool use real** (`herramientas.py` + loop en `brain.py`)
- `buscar_conocimiento`, `registrar_lead`, `crear_ticket`, `recordar_cliente`,
  `derivar_a_humano`, `crear_link_pago`
- Herramientas custom por agente via `tools.py` (lista `HERRAMIENTAS`)

**Etapa 3 — Cierre de ventas**
- Links de pago Wompi (`WOMPI_PRIVATE_KEY`); notificación de la venta al equipo

**Etapa 4 — Humanización**
- Burbujas cortas con pausas (`humanizar.py`, toggle `HUMANIZAR`)
- Notas de voz → texto con Whisper (`voz.py`, opcional con `OPENAI_API_KEY`)
- Memoria de largo plazo por cliente (tabla `clientes`, inyectada al system prompt)

**Etapa 5 — Parte del equipo**
- `derivar_a_humano` pausa el bot (`PAUSA_MINUTOS`) y avisa al asesor con contexto
- Avisos al equipo por WhatsApp (`ADMIN_PHONE`) para leads/tickets/pagos
- Reporte diario `GET /reporte?token=REPORTE_TOKEN` (para un cron de Railway)

## Decisiones

- **Modelo:** `claude-sonnet-5` por defecto (sucesor del Sonnet elegido para
  Ragnar por balance costo/calidad), configurable con `CLAUDE_MODEL`.
- **Voz con Whisper:** la API de Claude no acepta audio; Whisper es opcional y
  el bot pide el mensaje por texto si no está configurado.
- **Pagos solo Wompi** por ahora (mercado Colombia). Bold/MercadoPago cuando un
  cliente lo pida.
- **Sin panel/CRM todavía** (punto 14 de la visión) — los datos ya quedan en
  tablas `leads`/`tickets`/`clientes`, un panel puede leerlas después.
- El flujo no-code se mantiene: `CLAUDE.md` ahora solo entrevista y genera la
  capa fina.

## Verificación

- `python tests/test_core.py` — self-checks sin red: burbujas, firmas Twilio/Meta
  (vectores HMAC), esquemas de herramientas, memoria completa (historial,
  cliente, pausas, leads, tickets, resumen del día). ✅ Pasan.
- `from agentkit import main, chat, ...` importa limpio. ✅

## v0.2.0 (mismo día)

- **Canal Instagram DM** (`providers/instagram.py`): misma Graph API de Meta,
  firma compartida con WhatsApp, descarta ecos, soporta notas de voz. Variable
  de canal renombrada a `PROVIDER` (meta | twilio | instagram; se acepta
  `WHATSAPP_PROVIDER` como alias).
- **Pagos elegibles por el usuario**: Wompi (Colombia), MercadoPago (LatAm) y
  Stripe (global). Se detecta por la llave en .env; `PAGOS_PROVIDER` fuerza y
  `PAGOS_MONEDA` ajusta la moneda. La entrevista recomienda por país pero el
  usuario decide.
- **Entrevista**: ahora recomienda canal según el negocio (Twilio para probar,
  Meta para producción, Instagram para marcas con audiencia ahí), pasarela por
  país, y hosting según el caso (Railway default; Render/Fly/Cloud Run/VPS).

## v0.7.0 (2026-09-25) — Haiku por defecto, voz humana configurable y costo por agente

- **Modelo:** `claude-haiku-4-5` por defecto (alias de la API; `CLAUDE_MODEL=claude-haiku-4-5-20251001`
  fija la versión). Sonnet 5 solo con `CLAUDE_MODEL` explícito. Se conserva `cache_control`.
- **Voz de entrada:** OpenAI `gpt-4o-mini-transcribe` si hay `OPENAI_API_KEY`; Groq solo si
  `STT_PROVEEDOR=groq` o si no hay key de OpenAI (antes Groq tenía prioridad).
- **Voz de salida:** `TTS_PROVEEDOR` (openai por defecto, gemini de respaldo) con tabla de
  proveedores en `voz.py` para sumar otros sin reescribir. OpenAI con `TTS_VOZ` (default `marin`)
  y `TTS_INSTRUCCIONES` (default: español de Colombia, cálido y conversacional). Sigue en mp3.
  Pendiente la prueba de oído marin / coral / cedar.
- **Costo en USD por agente:** tabla `uso_api` (se crea sola al arrancar), una fila por llamada a
  Claude, STT o TTS. `agentkit/precios.py` con precios verificados en las páginas oficiales y
  override en `config/precios.json`. Todo con `Decimal`; un fallo al registrar solo se loguea.
  `GET /estado` agrega `costo_usd {hoy, mes, desglose}` (hora de Bogotá) sin tocar los campos previos.
- **Dependencias:** `sqlalchemy[asyncio]` (trae greenlet; un venv limpio fallaba sin él).
- Pruebas: `pytest -q` → 15 pruebas sin red ni APIs reales (y `python tests/test_core.py` corre además los self-checks async).

## Pendientes conocidos

- Verificar el shape exacto de los APIs de pago (Wompi payment_links,
  MercadoPago preferences, Stripe payment_links) con llaves reales antes del
  primer cobro en producción.
- Migrar **Ragnar** a esta base (su repo `nivaldyr-agente-whatsapp` sigue con el
  código generado de la versión anterior).
- Typing indicator real (Meta lo soporta; hoy la pausa es solo un `sleep`).
- Seguimiento proactivo (plantillas de Meta) — requiere número propio, fuera del
  sandbox de Twilio.
