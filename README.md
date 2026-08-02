# AgentKit — WhatsApp AI Agent Builder

Construye tu propio agente de WhatsApp con inteligencia artificial en menos de 30 minutos.
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
- **Cobrar por WhatsApp** con links de pago (Wompi, Colombia)
- Responder en **burbujas cortas con pausas**, como escribe una persona
- Entender **notas de voz** (transcripción con Whisper, opcional)
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
credenciales de WhatsApp…) y genera tu agente en una carpeta propia:

```
mi-agente/
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

## Stack

| Componente | Tecnología |
|-----------|-----------|
| Runtime | Python 3.11+ |
| Servidor | FastAPI + Uvicorn |
| IA | Anthropic Claude (`claude-sonnet-5` por defecto, con tool use) |
| WhatsApp | Meta Cloud API / Twilio |
| Base de datos | SQLite (local) / PostgreSQL (producción) |
| Voz | Whisper (OpenAI, opcional) |
| Pagos | Wompi (opcional) |
| Deploy | Docker + Railway |

## Desarrollo del core

```bash
python tests/test_core.py   # self-checks sin red ni API keys
```

---

Licencia: ver `LICENSE`.
