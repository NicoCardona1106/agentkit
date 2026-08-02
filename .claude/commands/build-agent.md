Lee el archivo CLAUDE.md completo. Contiene todas las instrucciones detalladas.

Ejecuta el flujo de onboarding de AgentKit siguiendo las 5 fases EN ORDEN.

IMPORTANTE: el código del agente NO se genera — vive en el paquete `agentkit/`
de este repo (core compartido). Tú solo generas la CAPA FINA del agente.

FASE 1 — Bienvenida y verificación del entorno
- Muestra el mensaje de bienvenida
- Verifica Python >= 3.11
- Pregunta el nombre del agente y crea su carpeta (ej: mi-agente/) con config/ y knowledge/
- Genera requirements.txt (instala agentkit desde este repo) e instala dependencias

FASE 2 — Entrevista del negocio
- Haz las preguntas UNA POR UNA (ver CLAUDE.md), espera cada respuesta
- Incluye las opcionales: pagos con Wompi y número del equipo (ADMIN_PHONE)

FASE 3 — Generación de la capa fina
- config/business.yaml y config/prompts.yaml (system prompt poderoso; menciona
  las herramientas del core y cuándo usarlas)
- tools.py SOLO si el negocio necesita herramientas propias
- .env con las variables que apliquen
- Dockerfile, docker-compose.yml y .gitignore
- NO generes agent/, brain.py, main.py ni providers — ya vienen en el core

FASE 4 — Testing local
- python -m agentkit.chat (desde la carpeta del agente)
- Ajusta prompts.yaml hasta que el usuario apruebe

FASE 5 — Deploy a Railway
- Solo si el usuario quiere
- Repo propio en GitHub + Railway + PostgreSQL + PUBLIC_URL + webhook del proveedor
- Opcional: cron para el reporte diario (GET /reporte?token=...)

REGLAS:
- Habla siempre en español
- Una pregunta a la vez
- Nunca hardcodees API keys
- No avances de fase sin confirmación
- Nunca modifiques el paquete agentkit/ para personalizar un agente
