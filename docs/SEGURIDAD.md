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

## Capas pendientes (por valor)
1. **Conocimiento limpio:** el agente puede decir TODO lo que está en `knowledge/` y en el prompt.
   Nada interno ahí (socios, márgenes, planes de recuperar equipos, costos). Auditar cada agente.
2. **Límite y tope por número en WhatsApp** (como ya tiene el chat web): mensajes por hora por
   teléfono y USD/día por agente, para que un número no queme la cuenta de Anthropic.
3. **Clave de Anthropic por agente con límite de gasto** en la consola: si una se filtra o un
   agente se desboca, el daño queda acotado y se sabe cuál fue.
4. **Filtro de salida con canario:** una cadena única en el prompt; si aparece en una respuesta,
   no se envía y se avisa (prueba dura de fuga de prompt).
5. **Montos validados en el servidor:** `crear_link_pago` solo con precios del catálogo, nunca un
   monto que invente el modelo.
6. **Datos personales:** no loguear teléfonos ni contenido completo en producción; retención de
   historial definida (Ley 1581).
7. Rotar claves expuestas (p. ej. `ADMIN_CODE` de /crear) y revisar accesos al VPS.
