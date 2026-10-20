# Modo borrador (v0.9.0)

El agente redacta la respuesta, pero **no se envía nada al cliente sin que una persona la apruebe**. Sirve
para cualquier agente y cualquier negocio: canales, aprobadores y bot se configuran en el `.env` de cada agente.
El chat web (`/chat`) no pasa por el modo borrador (ver README).

## Cómo funciona

1. Llega el mensaje del cliente → Claude redacta → se guarda un **borrador** y se avisa por cada canal de
   `BORRADOR_CANALES`.
2. Gana la **primera decisión**, venga del canal que venga (UPDATE atómico `WHERE estado='pendiente'`).
   Las demás reciben «ya fue resuelto».
3. Al decidir, el estado pasa a `enviando`; solo es `enviado` si TODAS las burbujas salieron. Si alguna
   falló: `fallo_envio` (ERROR en el log, cuenta en `errores_24h` de `/estado`, aviso «no se pudo enviar»).
   **No se reintenta y no vuelve a pendiente**: lo atiende una persona.

Estados: `pendiente`, `enviando`, `enviado`, `fallo_envio`, `descartado`, `reemplazado`, `vencido`.

## Variables

| Variable | Qué hace |
|---|---|
| `MODO_BORRADOR=true` | Activa el modo. **Falla cerrado**: aunque no quede ningún canal válido, nada se envía sin aprobación; los borradores quedan pendientes como «sin aviso» y al arrancar hay un ERROR. |
| `BORRADOR_CANALES` | Canales de aviso separados por coma: `whatsapp`, `telegram`. Sin la variable vale `whatsapp`. Un canal que no existe (sin su configuración) se ignora con una advertencia al arrancar. |
| `TELEGRAM_TOKEN` | Token del bot (BotFather). Un bot propio por agente. |
| `TELEGRAM_CHAT_ID` | Id del grupo privado donde llegan los borradores (número negativo). |
| `TELEGRAM_APROBADORES` | Ids numéricos de Telegram de quienes pueden decidir, separados por coma. Vacío o ausente: el canal `telegram` no existe y nadie decide. |

## Reglas por requisito

- **RF-52 canales múltiples.** El borrador va a todos los canales; gana la primera decisión.
- **RF-53 Telegram.** Botones **Aprobar** / **Descartar**. Para editar, se **responde al mensaje del borrador**
  con el texto nuevo: el bot pide confirmación («Enviar esta versión» / «Cancelar») y hasta que se confirma no
  se envía nada. Solo cuenta `message.text`; vacío, más de 4.096 caracteres (WhatsApp) o más de 1.000
  (Instagram) se rechaza con aviso. Al decidir, el mensaje se edita: queda el resultado y sin botones.
  Las decisiones llegan por `getUpdates` con espera larga (solo salida: **ningún puerto nuevo, ningún webhook**).
- **RF-54 autorizados.** Solo decide un id de `TELEGRAM_APROBADORES` **dentro** de `TELEGRAM_CHAT_ID`, sobre un
  mensaje que AgentKit registró (se guarda `tg_chat_id` + `tg_message_id`; el `callback_data` solo lleva la
  acción). Lo demás se ignora y se anota sin contenido (una línea por minuto por id).
- **RF-55 ninguno se pierde.** Si el aviso falla en un canal: WARNING. Si falla en todos: ERROR, el borrador
  queda pendiente y sale en `/estado` como `borradores_sin_aviso` y en el reporte diario.
- **RF-56 Instagram.** Con `PROVIDER=instagram`, `ADMIN_PHONE` no es aprobador (`es_admin` es siempre falso),
  `whatsapp` no es un canal válido y no sale ninguna llamada hacia ese número. Usa `BORRADOR_CANALES=telegram`.
- **RF-57 vencimiento.** El borrador vence 23 h 45 min después del **último mensaje del cliente** (la ventana
  de 24 h menos 15 min). Un borrador vencido, reemplazado o ya resuelto se rechaza **en la decisión**, aunque el
  barrido (cada minuto) no haya corrido; en Telegram el mensaje pasa a «vencido». Un pendiente de v0.8.11 (sin
  `vence`) vence a `creado + 23 h 45 min`.
- **Envíos huérfanos.** Si cancelan la tarea a mitad del envío el borrador pasa a `fallo_envio` al instante; si el
  proceso muere (o la base falla) y queda en `enviando` más de 10 min, el barrido lo pasa a `fallo_envio`, anota
  un ERROR («quedó a mitad del envío: revisar si el cliente lo recibió») y deja el aviso de Telegram con
  «no se pudo confirmar el envío».
- **RF-58 un pendiente por conversación.** Índice único parcial `(telefono) WHERE estado='pendiente'`. Si el
  cliente escribe de nuevo antes de la decisión, el borrador nuevo reemplaza al anterior (que queda
  `reemplazado`, y su mensaje de Telegram también) y el aviso junta todos los mensajes sin responder.
  Esto aplica también sin `BORRADOR_CANALES`.

## Qué cambia frente a v0.8.11 (también sin `BORRADOR_CANALES`)

1. Un solo pendiente por conversación: el borrador nuevo reemplaza al anterior.
2. Vencimiento a las 23 h 45 min del último mensaje del cliente.
3. Si el envío falla (alguna burbuja), el borrador queda en `fallo_envio` con un ERROR y un aviso «no se pudo
   enviar»; ya no se da por enviado. Si una burbuja falla no salen las siguientes.
4. Instagram: `ADMIN_PHONE` deja de ser aprobador y de recibir avisos por el proveedor de Instagram (ni los del
   modo borrador ni los del equipo: leads, tickets, reporte, tope).
5. Falla cerrado: con `MODO_BORRADOR=true` y sin ningún canal válido (p. ej. sin `ADMIN_PHONE`) el agente ya NO
   responde solo: el borrador queda pendiente y sin aviso.
6. Los avisos al equipo (derivar a humano, tope, lead, ticket, pago) llevan el teléfono **completo**, para poder
   contactar al cliente; llegan también al chat de `TELEGRAM_CHAT_ID`, que debe ser un grupo privado solo con el equipo.
   Solo el aviso del borrador va enmascarado.
7. Los logs de Meta e Instagram registran `HTTP <código>` y el código de error de Graph, no el cuerpo.

## Privacidad

- El aviso de Telegram lleva el nombre que dio el cliente y los **últimos 4 dígitos**, nunca el número
  completo; sin `parse_mode` (el texto del cliente se ve tal cual, sin formato ni enlaces activos). El aviso por
  WhatsApp al admin sigue mostrando el número, como antes.
- Los logs no llevan el texto del cliente ni del borrador, ni cuerpos de respuestas de Telegram, ni el error de
  httpx (su URL lleva el token): solo el nombre de la excepción. El teléfono va con `ocultar`.
- Telegram es sub-encargado de datos: recibe el borrador y el texto del cliente y los guarda en sus servidores.
  Decirlo en la cláusula de tratamiento de datos de cada negocio.
- Cada decisión guarda `decidido_por` (`telegram:<id>` o `admin`) y `canal`.

## Operación

- **Un solo proceso sondea cada bot** (un worker de uvicorn): dos procesos con el mismo token se quitan los
  updates y Telegram responde 409. Si `getUpdates` da 409 de forma repetida queda un ERROR en `/estado`. Tampoco
  puede haber un webhook configurado en ese bot.
- Un bot por agente. No compartir el token con otro proceso que haga `getUpdates`.
- Telegram no abre vista previa de los enlaces del cliente (`link_preview_options.is_disabled`); el enlace sigue
  siendo clicable, así que **tocarlo es decisión de quien aprueba**.
- Un **administrador anónimo** del grupo (que escribe «como el grupo») no puede decidir ni editar: Telegram no
  manda su id, y los mensajes con `sender_chat` se ignoran. Debe desactivar «Permanecer anónimo» en el grupo.
- Sin red, el sondeo espera cada vez más (5, 10, 20, 40 y 60 s). Tres respuestas 401/404 seguidas (token
  revocado o mal puesto) dejan un ERROR en `/estado`, igual que el 409.
- **`comando_admin` por WhatsApp sigue activo** para el `ADMIN_PHONE` (es el aprobador del canal WhatsApp):
  `ok N` / `no N` / `editar N texto`, aunque `whatsapp` no esté en `BORRADOR_CANALES`. Así un borrador pendiente
  creado con v0.8.11 se sigue decidiendo por WhatsApp tras actualizar. Quien no quiera esa vía no debe poner
  `ADMIN_PHONE` (los avisos del equipo irán solo por Telegram).
- El aviso de más de 4.096 caracteres se parte en varios mensajes: los del cliente se acotan, el borrador va
  completo y los botones van en la última parte (es el mensaje al que se responde para editar).
- La tabla `borradores` se migra sola al arrancar (columnas nuevas nulas; índice único creado si no existe; si
  una base vieja tenía varios pendientes de la misma conversación, queda el más reciente).

## Activar Telegram en un agente

1. En Telegram, `@BotFather` → `/newbot` → guardar el token. Luego `/setprivacy` → el bot → **Enable**
   (modo privacidad activado: el bot solo recibe los comandos, las respuestas a sus mensajes y los botones).
2. Crear un grupo **privado** solo con los aprobadores y agregar el bot.
3. Sacar los ids (con el agente apagado, para que nadie más consuma los updates). Con el modo privacidad, el
   bot solo ve comandos y respuestas a sus mensajes: en el grupo cada persona escribe `/start@<nombre_del_bot>`
   (o responde a un mensaje del bot). Luego, **en el servidor con `curl`, nunca en el navegador** (el token
   quedaría en el historial): `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"`. `message.chat.id`
   es el del grupo (negativo) y `message.from.id` el de cada persona. Esos `/start` sin confirmar llegan al
   agente al arrancar y se ignoran (no son respuestas a un borrador).
4. En el `.env` del agente: `MODO_BORRADOR=true`, `BORRADOR_CANALES=telegram` (o `telegram,whatsapp`),
   `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_APROBADORES`. Reiniciar con un solo worker y revisar que el
   log de arranque no traiga advertencias de `BORRADOR_CANALES`.
5. Probar con un mensaje de prueba: debe llegar el aviso con botones; Aprobar envía, Descartar no.
