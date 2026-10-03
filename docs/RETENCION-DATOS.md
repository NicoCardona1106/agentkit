# Retención y borrado de datos personales en los agentes (Ley 1581) — PROPUESTA

> **Estado: BORRADOR para que Nicolas apruebe (2026-10-03). Sin código hasta aprobarlo.**
> No es asesoría legal ni lo revisó un abogado. Las normas citadas (Ley 1581 de 2012, Decreto 1377 de
> 2013 compilado en el Decreto 1074 de 2015) hay que verificarlas vigentes en suin-juriscol.gov.co o
> sic.gov.co antes de publicar cualquier texto a un cliente.

## 1. Quién es quién (importa para los textos)
- **Responsable del tratamiento:** el negocio dueño del agente (Ragnar, Valentina, Cora, etc.). Es quien
  decide para qué se usan los datos de sus clientes, y la política y el aviso van **a su nombre**.
- **Encargado:** Nicolas / Co-axis, que opera el agente y la base por cuenta del negocio. Conviene una
  cláusula de tratamiento de datos en el contrato con cada negocio (qué hacemos, qué no, plazos de abajo).
- **Subencargados** (reciben datos para que el agente funcione; casi todos fuera de Colombia, es decir,
  transmisión internacional): Anthropic (Claude: cada mensaje), Meta (WhatsApp/Instagram) o Twilio
  (canal), OpenAI (notas de voz y voz de salida, si se activan), Groq o Gemini (respaldos de voz, solo si
  se configuran), el servidor (VPS de maxxcontrol o Railway) y Telegram (avisos al equipo, si se usa).
  No sé con certeza cuánto guarda cada uno: hay que leer su política de retención vigente y citarla.

## 2. Qué guarda hoy el core y por cuánto
Hoy **todo se guarda para siempre**, y no hay forma de borrar a una persona sin entrar a la base a mano.

| Tabla | Qué tiene | Propuesta de plazo | Por qué |
|---|---|---|---|
| `mensajes` | Cada mensaje del cliente y del agente (las notas de voz quedan como texto transcrito) | **12 meses** desde el último mensaje de esa persona | El agente necesita contexto de la conversación; un año cubre clientes recurrentes y reclamos. Si en 12 meses no escribe, se borra toda su conversación. |
| `clientes` | Nombre y notas que el agente aprende de la persona | **12 meses** sin actividad (igual que su conversación) | Es la «memoria» del cliente: sin conversación no tiene uso. |
| `leads` | Nombre, interés, presupuesto, contacto | **24 meses** desde su creación | Es la base comercial del negocio; el negocio puede pedir menos. |
| `tickets` | Problema reportado | **24 meses** desde su creación | Soporte posventa y garantías. |
| `borradores` | Respuestas propuestas en modo borrador | **30 días** | Solo sirven mientras el admin aprueba. |
| `pausas` | Teléfono y hasta cuándo está derivado | **Se borra al vencer** | No tiene uso después. |
| `uso_api` | Costos por llamada, con el teléfono | **Quitar el teléfono a los 90 días** (la fila de costo se queda) | El costo se necesita para facturar e informes; el teléfono solo para revisar abusos recientes. |
| `mensajes_procesados` (v0.8.9) | Solo ids de mensajes | 7 días (ya implementado) | No identifica a nadie por sí solo. |
| Logs del servidor | Teléfono enmascarado, sin textos (v0.8.8) | **30 días** en journald/Railway | Se configura en el servidor, no en el core. |

Las cifras son una propuesta razonable, no un número que diga la ley: la ley pide guardar solo lo
necesario para la finalidad y el tiempo que sea razonable. Nicolas decide; cada negocio puede pedir otros
plazos en su `.env`.

## 3. Cómo funcionaría (cuando se apruebe)
1. **Purga automática** una vez al día (al hacer el reporte diario o al arrancar), con los plazos de la
   tabla. Configurable por agente con variables tipo `RETENCION_MENSAJES_DIAS`; sin las variables, los
   plazos por defecto de arriba. Cambiar esto **sí cambia** un agente existente al actualizar el core (borra
   lo viejo la primera vez): por eso se anuncia antes a cada negocio y se hace respaldo de la base antes.
2. **Borrado a pedido de la persona** (derecho de supresión):
   - La persona lo pide por el canal del negocio (WhatsApp, correo). El agente NO borra por sí solo cuando
     alguien escribe «borra mis datos» (cualquiera podría pedirlo por otro número o por manipulación):
     le responde cómo se tramita y avisa al equipo.
   - El admin lo ejecuta con un comando por WhatsApp desde `ADMIN_PHONE` (p. ej. `borrar +57…`) que pide
     confirmación y borra a esa persona de **todas** las tablas (mensajes, cliente, leads, tickets,
     borradores, pausas, y el teléfono de `uso_api`), y responde cuántas filas se fueron.
   - Queda en el log solo «supresión ejecutada para ***1234» y la fecha, como evidencia de que se cumplió.
   - Plazo legal de respuesta a un reclamo: 15 días hábiles (prorrogables 8 informando). Lo que ya se envió
     a los subencargados (Anthropic, Meta, OpenAI…) se rige por sus propios plazos; el texto al titular
     debe decirlo sin prometer lo que no controlamos.
3. **Consulta** (la persona pide saber qué tenemos de ella): el mismo comando con `datos +57…` le da al
   admin un resumen para responderle. Plazo legal: 10 días hábiles (prorrogables 5).

## 4. Qué decir al cliente final
**Aviso corto** (primer mensaje del agente a un número nuevo, una sola vez, en el tono del negocio):

> «Hola, soy [AGENTE], asistente virtual de [NEGOCIO]. Para atenderte guardamos esta conversación y los
> datos que nos compartas, y usamos servicios de inteligencia artificial que pueden procesarlos fuera de
> Colombia. Puedes consultar, corregir o pedir que borremos tus datos escribiéndonos aquí o a [CORREO].
> Política: [LINK]»

Pendiente de decidir: si seguir escribiendo cuenta como autorización (conducta inequívoca) o si hay que
pedir un «sí» explícito antes de responder. Lo segundo es más seguro jurídicamente pero espanta a parte de
los clientes; **es una de las preguntas para el abogado**.

**Política de tratamiento** (página del negocio, a su nombre) debe incluir como mínimo (Decreto 1377):
responsable con NIT o cédula, dirección, correo y teléfono; qué datos trata el agente y para qué
(responder consultas, cotizar, agendar, soporte, avisos al equipo); los plazos de la tabla; los
subencargados y que hay transmisión internacional; los derechos (conocer, actualizar, rectificar,
suprimir, revocar) y el canal real para ejercerlos; fecha de vigencia. Datos sensibles (salud, por
ejemplo en un consultorio) y menores: el agente no debe pedirlos; si el negocio los necesita, va aparte.

## 5. Preguntas para Nicolas
1. ¿Aprobados los plazos de la tabla (12 / 24 / 30 días / 90 días)?
2. ¿Aviso corto al primer mensaje, o pedir un «sí» explícito antes de atender?
3. ¿Comando de borrado por WhatsApp del admin, o prefieres que el borrado se haga solo desde NccHUB
   (cuando exista el panel de agentes)?
4. ¿Agregamos la cláusula de encargado al contrato de cada agente (`docs/contratos` de NccHUB)?
5. ¿Revisión de abogado antes de publicar la política a los negocios, o autorrevisión como con los
   contratos de Reflexcam?
