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

## 2. Voz: que suene humana ante todo (actualizado 2026-09-25, core v0.7.1)

- Meta de AgentKit: el cliente nunca debe sentir que habla con un bot. En la voz manda que suene
  humana; el precio va después.
- Entrada: `gpt-4o-mini-transcribe` (USD 0,003/min) por defecto cuando hay `OPENAI_API_KEY`.
  Groq solo como respaldo (`STT_PROVEEDOR=groq` o sin key de OpenAI).
- Salida: **OpenAI `gpt-audio-1.5`, voz `marin` (femenina)**, la muestra «O3» elegida por Nicolas
  en la prueba de oído a ciegas del 2026-09-25 (sucede a Gemini `Kore`, elegida en la ronda
  anterior del mismo día). Modelo conversacional por Chat Completions con audio, con el estilo
  «fluido» (español de Colombia, cálido, de corrido, nada de locutor ni robot) y la orden de decir
  el texto palabra por palabra. Regla: que se sienta humano en todo momento; calidad antes que precio.
- **Costo: ~USD 0,08 por minuto de voz** (~USD 9 por cliente al mes a 500 respuestas en voz), ~5×
  el TTS barato (USD 0,015/min). **Tenerlo en cuenta en la mensualidad** de los clientes que usen
  voz. El costo real de cada respuesta queda en `uso_api` desde el `usage` de OpenAI.
- **Guarda de fidelidad:** el modelo es conversacional y puede cambiar el texto. El core compara la
  transcripción que devuelve el propio modelo (no un reconocimiento del mp3) con lo pedido: números,
  negaciones y días deben coincidir exactos y el resto con similitud ≥ 0,9 (≥ 0,95 en textos
  largos); si no, el audio se descarta y habla el respaldo. Reduce mucho el riesgo de un precio o
  un «no» cambiado, pero no lo elimina (un sustantivo cambiado en un texto largo puede pasar).
- **Respaldo automático:** `gpt-4o-mini-tts` (voz `marin`) y luego Gemini `Kore` si hay
  `GEMINI_API_KEY`; si todo falla, la respuesta sale en texto. Todo configurable sin tocar código
  (`TTS_PROVEEDOR`, `TTS_VOZ`, `TTS_INSTRUCCIONES`).
- **Personaje femenino:** con la voz `marin`, el agente se presenta como mujer (nombre y forma de
  hablar); la entrevista del core lo pide.
- Cuando el cliente manda nota de voz, el agente escribe esa respuesta en frases de corrido con
  pocas comas (así sonó la muestra).
- **Advertencia:** si se usa el respaldo Gemini, la `GEMINI_API_KEY` debe ser de un proyecto con **facturación activa** (tier de
  pago). En el tier gratis Google puede usar los datos para entrenar, lo que choca con la Ley 1581
  frente al cliente (por eso Gemini gratis sigue descartado en la def. 3).
- `gemini-3.8-flash-tts` es la sucesora si el preview se retira: lee el texto literal (pide el
  estilo en `speech_metadata`) y devuelve WAV, así que el cambio requiere ajustar el core y repetir
  la prueba de oído.
- Deepgram/ElevenLabs únicamente si un cliente lo pide y lo paga.
- Costo registrado por agente: cada transcripción y cada síntesis quedan en la tabla `uso_api`
  con su costo en USD (ver def. 3).

## 3. Modelo de lenguaje: Claude Haiku 4.5 con prompt caching, Sonnet 5 en escalada

- `claude-haiku-4-5` es el default del core desde v0.7.0 (antes había que fijarlo en el .env);
  respuestas cortas (MAX_TOKENS 512), system prompt cacheado.
- Sonnet 5 solo para casos difíciles (escalada explícita), nunca por defecto.
- Medido 2026-09-08: ~2.100 tokens de entrada y 30-50 de salida por respuesta → ≈ USD 0,0024 por
  respuesta ≈ USD 4-5/cliente/mes a 300 conversaciones. El core ya manda `cache_control`, pero
  Haiku 4.5 solo cachea prefijos ≥ 4.096 tokens (Sonnet 5: ≥ 1.024): un agente pequeño no cachea
  (verificado: 0 creados); cuando el conocimiento crezca, la parte fija baja al 10 % sola.
- Gemini gratis descartado (entrena con datos). Qwen local solo si algún día hay GPU.
- **Costo registrado por agente (v0.7.0):** cada llamada a Claude guarda en `uso_api` el `usage`
  real (entrada, salida, caché leída y escrita) y su costo en USD con `Decimal`; `GET /estado`
  devuelve `costo_usd` (hoy y mes en hora de Bogotá, desglose llm/stt/tts). Así la mensualidad
  se valida con el gasto real de cada cliente, no con estimaciones. Precios en
  `agentkit/precios.py` (verificados 2026-09-25) y corregibles con `config/precios.json`.

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
