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

## Pendientes conocidos

- Verificar el shape exacto del API de payment_links de Wompi con una llave real
  antes del primer cobro en producción.
- Migrar **Ragnar** a esta base (su repo `nivaldyr-agente-whatsapp` sigue con el
  código generado de la versión anterior).
- Typing indicator real (Meta lo soporta; hoy la pausa es solo un `sleep`).
- Seguimiento proactivo (plantillas de Meta) — requiere número propio, fuera del
  sandbox de Twilio.
