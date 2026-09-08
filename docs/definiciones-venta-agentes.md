# Definiciones para vender agentes de WhatsApp (AgentKit + Hermes)

Confirmadas por Nicolas Cardona: 2, 3 y 4 el 2026-09-06; 1 y 5 el 2026-09-08.
Fuentes: investigación "Hermes" (2026-08-23) y notas de WhatsApp API de octubre 2026 (2026-09-06).
Este documento manda sobre cualquier nota anterior; se cambia por decisión explícita.

## 1. Canal de WhatsApp: Meta Cloud API directa, como proveedor de tecnología

- Una sola app de Meta (Nicolas Agents, id 1039003702291031) registrada como Tech Provider.
- Alta de clientes por **Embedded Signup v4** desde https://ncchub.dev/conectar. Nunca WABA
  prestado ni número del portafolio de Nicolas para un cliente.
- Cada cliente es dueño de su WABA y su número, y **paga su consumo de Meta con su tarjeta**
  (Tech Provider no tiene línea de crédito). Presupuestar "menos de 10.000 COP/mes en uso normal".
- Cada WABA se suscribe a la app con su propia URL de webhook (`override_callback_uri`), así cada
  agente corre aislado en `<cliente>.agentes.ncchub.dev`.
- Twilio no es opción de producción. Queda solo como sandbox de demo si Meta no está disponible.

## 2. Voz: solo OpenAI

- Entrada `gpt-4o-mini-transcribe`, salida `gpt-4o-mini-tts` (~USD 2/cliente/mes).
- Deepgram únicamente si un cliente lo pide y lo paga.

## 3. Modelo de lenguaje: Claude Haiku 4.5 con prompt caching, Sonnet 5 en escalada

- `CLAUDE_MODEL=claude-haiku-4-5`, respuestas cortas (MAX_TOKENS 512), system prompt cacheado.
- Sonnet 5 solo para casos difíciles (escalada explícita), nunca por defecto.
- Medido 2026-09-08: ~2.100 tokens de entrada y 30-50 de salida por respuesta → ≈ USD 0,0024 sin
  caché; con caché del system prompt ≈ USD 1-1,5/cliente/mes a 300 conversaciones.
- Gemini gratis descartado (entrena con datos). Qwen local solo si algún día hay GPU.

## 4. Despliegue: VPS + Hermes cuando haya el primer cliente pago

- Hasta entonces, demos en el PC de Nicolas (uvicorn + túnel cloudflared).
- VPS recomendado: OVH VPS-2. Docker, Caddy (subdominios + HTTPS), Postgres, backups fuera de la
  máquina, Uptime Kuma. Un docker-compose por agente.

## 5. Segmento pequeño: Coexistence, con plan B de número dedicado

- Negocios que solo usan la app WhatsApp Business en el celular: se conecta **el mismo número**
  (Coexistence vía Embedded Signup v4 con "usuarios de la app WhatsApp Business"). Dueño y bot
  responden en el mismo chat; se sincronizan 180 días de historial.
- Expectativas por escrito: sin grupos ni catálogo por API, difusiones de solo lectura, 20 msg/s,
  abrir la app al menos cada 13 días, tarjeta propia en Meta.
- Plan B si Meta no admite Coexistence para ese número: número nuevo dedicado al bot y mensaje de
  ausencia en el número viejo.
- Nunca vías no oficiales (Baileys, Evolution, web.whatsapp automatizado) a clientes pagos.

## Modelo comercial (decidido 2026-09-06)

- Instalación cobrada aparte + **mantenimiento mensual fijo** por cliente, cobrado por Mercado
  Pago (suscripción). Costo directo estimado por cliente pequeño: USD 5-8/mes (IA + Meta + VPS
  compartido). Mensualidad orientativa 100-150k COP, a validar con el primer mes real de la barbería.
- Contrato de servicio con anexo de tratamiento de datos (Ley 1581: el cliente es responsable,
  Nicolas encargado). Si el cliente entra por Reflexcam, reparto 60/20/20.

## Pendientes de core derivados

- `brain.py`: `cache_control` en el bloque `system` (def. 3).
- `main.py` / `providers/meta.py`: 403 con verify token incorrecto; no hacer `int()` del reto.
- Embedded Signup v4 (canje de `code`, `account_update`), webhooks de Coexistence (`history`,
  `smb_app_state_sync`, `smb_message_echoes`) y lectura de `pricing` en los webhooks de estado.
