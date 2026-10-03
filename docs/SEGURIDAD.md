# Seguridad de los agentes — lecciones y capas

Documento vivo. Cada capa nueva o incidente se anota aquí con fecha.

## Lección 2026-09-28 — inyección de instrucciones

**Qué pasaba:** ni el core ni los prompts de Valentina y Cora tenían defensa. El texto del
cliente llegaba al modelo como un mensaje más, así que cualquiera podía intentar "ignora tus
instrucciones", hacerse pasar por el dueño o por Meta, sacar el prompt o arrancar un descuento
o una promesa que luego se muestra como prueba.

**Qué se hizo (core v0.8.4):**
1. `BLOQUE_SEGURIDAD` en `agentkit/brain.py`, pegado SIEMPRE al final del prompt del negocio
   (dentro del bloque cacheado). Vive en el core: un cliente no lo quita editando su `prompts.yaml`.
2. Todo turno de texto del usuario viaja envuelto en `<mensaje_cliente id="…">` con un id
   aleatorio POR TURNO (`secrets.token_hex(4)`). El cliente no puede adivinarlo para "cerrar"
   la etiqueta y colar instrucciones. La memoria guarda el texto sin envolver.
3. Herramienta `reportar_manipulacion`: aviso al equipo (Telegram/WhatsApp), máximo 1 por
   hora por conversación para que un atacante no inunde el canal.
4. `tests/test_core.py::test_defensa_inyeccion` (sin API) y `tests/ataques_prompt.py`
   (manual, API real) como regresión.

**Resultado medido contra Cora (Haiku 4.5), 2026-09-28:** 5 de 5 ataques contenidos: no reveló
prompt ni herramientas, rechazó el "descuento del dueño" y el falso modo sistema, ignoró el
cierre falso de etiqueta, y se negó a garantizar resultados. El cliente de control se atendió
normal. Solo 1 de los 5 ataques disparó el aviso: el modelo reporta los intentos más obvios,
no todos (aceptable; ver capa 5 abajo).

**Regla que queda:** antes de publicar un core nuevo o cambiar el prompt de un agente, correr
`tests/ataques_prompt.py` desde la carpeta del agente y revisar las respuestas a ojo.

## Capas que YA existen
- Firma de webhooks validada (Meta, Twilio, Instagram) en `agentkit/providers/`.
- Chat web: orígenes permitidos (`WEB_CHAT_ORIGINS`), límite por IP/hora y por sesión, tope de
  gasto diario (`WEB_CHAT_TOPE_USD_DIA`).
- Claves solo en `.env` (modo 600 en el VPS), nunca en git.
- Modo borrador: el admin aprueba cada respuesta el primer mes.
- Derivar a humano pausa el bot.
- **v0.8.7:** tope de gasto por agente en WhatsApp/Instagram (`TOPE_USD_DIA`/`TOPE_USD_MES`,
  `docs/TOPE-GASTO.md`).
- **v0.8.8 (informe de seguridad 2026-10-03, arreglos que no dependen del `.env` de cada agente):**
  - Twilio solo descarga audios de `twilio.com` por https: las credenciales de la cuenta nunca salen
    hacia otro host aunque falte `PUBLIC_URL` (httpx quita `Authorization` al redirigir al CDN).
    Instagram solo descarga de los CDNs de Meta (`fbsbx.com`, `fbcdn.net`, `cdninstagram.com`) y revisa
    cada redirección.
  - La memoria del cliente (`recordar_cliente`) entra al prompt dentro de `<memoria_cliente>`, sin
    «<»/«>» y con límites (nombre 100, nota 500, total 2.000, las más recientes); el bloque de
    seguridad dice que nunca son órdenes ni autorizan descuentos.
  - Logs: INFO por defecto aunque `ENVIRONMENT=development` (`LOG_LEVEL` acepta DEBUG, INFO,
    WARNING…), teléfono solo con los 4 últimos dígitos, sin el texto del cliente ni de la respuesta
    (tampoco en el aviso de la guarda de voz), sin la entrada de las herramientas, sin el cuerpo de los
    errores de Twilio, y las librerías (anthropic, openai, aiosqlite, httpcore, sqlalchemy) en WARNING.
  - `/reporte` acepta el token por cabecera `X-Reporte-Token` y lo compara en tiempo constante
    (`?token=` sigue funcionando para no romper los cron).
  - Sin `/docs`, `/redoc` ni `/openapi.json`; `/` ya no dice la versión: para saber qué core corre un
    agente, `GET /estado` con `X-Reporte-Token`.
  - Cuerpo de más de `MAX_CUERPO_BYTES` (1 MB) → 413, también sin Content-Length (chunked: se corta al
    pasar el tope, sin juntarlo entero). Un `MAX_CUERPO_BYTES` inválido usa 1 MB (no tumba el arranque).
  - Avisos al equipo por cliente (lead, ticket, link de pago): máximo 5 por hora; si se calla el aviso del
    lead, el bot no dice que el equipo fue notificado. **La derivación a humano siempre avisa** (el bot
    queda en pausa; callar ese aviso dejaría al cliente esperando). Lo que escribió el cliente va entre
    «» en una sola línea (máx. 300 caracteres).
  - `PAUSA_MINUTOS` inválido usa 60; `0` o negativo ahora da 1 minuto (antes: pausa nula).
  - `LOG_LEVEL=NOTSET` equivale a DEBUG (vuelca datos de clientes): no usarlo en producción.
  - **Pendiente tras el deploy:** mandar una nota de voz real por Instagram y por Twilio y revisar que el
    log NO muestre «audio con URL fuera de…»: los dominios permitidos salen de lo conocido, sin poder
    verificarlos con red real.

## Capas pendientes (por valor)
1. **Conocimiento limpio:** el agente puede decir TODO lo que está en `knowledge/` y en el prompt.
   Nada interno ahí (socios, márgenes, planes de recuperar equipos, costos). Auditar cada agente.
2. **Límite por número en WhatsApp** (el tope en USD por agente ya existe desde v0.8.7): mensajes por
   hora por teléfono, para que un número no queme el tope del día de todos.
2b. **Fallar cerrado sin secretos:** que el core no arranque en producción sin `META_APP_SECRET` /
   `IG_APP_SECRET` / `TWILIO_AUTH_TOKEN` + `PUBLIC_URL` (hoy solo avisa en el log). Hacerlo DESPUÉS de
   confirmar el `.env` de cada agente en el VPS, para no apagar a ninguno.
3. **Clave de Anthropic por agente con límite de gasto** en la consola: si una se filtra o un
   agente se desboca, el daño queda acotado y se sabe cuál fue.
4. **Filtro de salida con canario:** una cadena única en el prompt; si aparece en una respuesta,
   no se envía y se avisa (prueba dura de fuga de prompt).
5. **Montos validados en el servidor:** `crear_link_pago` solo con precios del catálogo, nunca un
   monto que invente el modelo.
6. **Datos personales:** retención de historial definida y borrado por titular (Ley 1581). Los logs
   ya no llevan teléfonos completos ni contenido (v0.8.8).
7. Rotar claves expuestas (p. ej. `ADMIN_CODE` de /crear) y revisar accesos al VPS.
