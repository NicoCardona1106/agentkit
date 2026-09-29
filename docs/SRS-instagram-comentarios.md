# SRS — Instagram: «comenta y te llega por DM» (AgentKit) y métricas por cuenta (NccHUB)

Versión 1.1 · 2026-09-29 · Autor: Nicolas Cardona (redactado con Claude)

Dueño: Nicolas Cardona (AgentKit, NccHUB y app de Meta «Nicolas Agents») · Estado: BORRADOR

## 1. Introducción

**1.1 Propósito.** Define qué hará el módulo de Instagram de AgentKit que responde por mensaje directo a quien comenta una palabra clave en una publicación, la vista de métricas de Instagram por cuenta dentro de NccHUB, y qué hay que entregar a Meta para aprobar los permisos. Va dirigido a Nicolas (aprobación) y a quien lo construya (Claude/Codex).

**1.2 Alcance.**

Qué hace:

- Conecta una cuenta profesional de Instagram al agente con **Instagram Login**, sin página de Facebook.
- Recibe los comentarios de las publicaciones y reels de esa cuenta.
- Cuando un comentario contiene una palabra clave configurada, envía **un mensaje directo fijo** a quien comentó, con el recurso o el enlace prometido.
- Opcionalmente responde **en público** al comentario («¡Te escribí por DM!»).
- Si la persona responde el DM, el agente de AgentKit conversa como en WhatsApp, dentro de la ventana de 24 h.
- Migra los DMs de Instagram que hoy usan la vía de Facebook a Instagram Login.
- En **NccHUB**, conecta la cuenta de Instagram de cada cliente y muestra sus métricas de los últimos 30 días: seguidores, alcance, vistas, interacciones y las mejores publicaciones.
- Deja listo el material para el App Review de Meta, con los 4 permisos en una sola revisión.

Qué NO hace:

- Comentarios de transmisiones en vivo.
- Menciones en historias.
- Publicar contenido.
- Campañas masivas a quien no comentó.
- Un panel web para editar palabras clave: se configuran en un archivo del agente.
- En las métricas: reportes en PDF, comparación entre clientes, métricas de anuncios, historias en vivo y alertas.
- Varios clientes conectándose solos desde una interfaz pública: en la v1, la conexión la hace Nicolas o el cliente con un enlace que le da Nicolas.

**1.3 Definiciones.**

- **Cuenta conectada:** la cuenta profesional de Instagram del negocio.
- **Respuesta privada (private reply):** DM que Meta permite enviar como respuesta a un comentario.
- **Regla:** palabra clave más el mensaje y la respuesta pública que le corresponden.
- **Ventana de 24 h:** plazo en que el negocio puede seguir escribiendo después del último mensaje del usuario.

**1.4 Referencias.**

- Documentación de Meta: [Private Replies](https://developers.facebook.com/docs/instagram-platform/private-replies) (Instagram Platform).
- `CLAUDE.md` y `README.md` de AgentKit.
- Memoria «App de Meta Nicolas Agents»: App Review de WhatsApp aprobado el 2026-09-14; la app sigue sin publicar.
- `SEMANA.md`, sección Venta de agentes.
- Referencia de mercado: el post de @ramiro.cubria del 2026-09-20 (1,8K comentarios vendiendo exactamente esto).

## 2. Descripción general

**2.1 Perspectiva.** Es una extensión del core de AgentKit, no un sistema nuevo:

- Reutiliza el agente, la memoria, los avisos al equipo, el costo en `uso_api` y la defensa contra inyección.
- Se integra con la app de Meta «Nicolas Agents», con el producto «Instagram API with Instagram Login», y con los webhooks de Instagram (campos `comments` y `messages`).

**2.2 Funciones principales.**

1. Conectar una cuenta de Instagram y guardar su token; el token se renueva solo.
2. Recibir el webhook de comentarios y validar su firma.
3. Detectar la palabra clave.
4. Enviar el DM fijo una sola vez por comentario, dentro del plazo de 7 días.
5. Opcionalmente, responder en público.
6. Si el usuario contesta, conversar con el agente.
7. Avisar al equipo y registrar el lead.
8. En NccHUB, mostrar las métricas de Instagram de cada cliente.
9. Dejar los videos y los textos del App Review.

**2.3 Usuarios y roles.**

- **Nicolas:** configura, conecta cuentas y graba la revisión.
- **Negocio cliente:** dueño de la cuenta de Instagram; autoriza con Instagram Login.
- **Persona que comenta:** usuario de Instagram que no sabe que hay un bot hasta que recibe el DM.
- **Socios de NccHUB (Nicolas, Juan):** ven las métricas de las cuentas de sus clientes.
- **Revisor de Meta:** ve los videos y las instrucciones.

**2.4 Entorno.**

- El agente corre en su VPS (el de Co-Axis o el propio), detrás de HTTPS público (Caddy o túnel), como los agentes de WhatsApp.
- El webhook y el callback de OAuth necesitan URL pública estable.
- Cuenta de prueba y de video: **Reflexcam** (profesional), agregada como probadora de la app.

**2.5 Restricciones.**

- **Límites de Meta:**
  - 1 respuesta privada por comentario;
  - dentro de 7 días desde el comentario;
  - 750 respuestas privadas por hora por cuenta;
  - mensajes de seguimiento solo dentro de las 24 h desde el último mensaje del usuario;
  - la cuenta debe ser profesional.
- **Antes de la aprobación:** solo funcionan las cuentas con rol en la app (administrador, desarrollador o probador).
- **Legal:** Ley 1581 (habeas data), porque se guardan el ID y el nombre de usuario de quien comenta.
- **Sin dependencias nuevas de pago.**

**2.6 Supuestos y dependencias.**

- La verificación de empresa de «Nicolas Agents» está vigente; se hizo con el alta como proveedor de tecnología. Verificarlo en el panel antes de enviar.
- Juan da acceso a la cuenta de Instagram de Reflexcam para la prueba.
- La app se publica (modo Activo) antes o junto con la revisión; hoy está sin publicar.
- Política de privacidad pública: https://ncchub.dev/privacidad, con eliminación de datos.
- Los permisos pedidos a Meta son `instagram_business_basic`, `instagram_business_manage_comments`, `instagram_business_manage_messages` e `instagram_business_manage_insights`.
- El agente y NccHUB se conectan cada uno por su lado, con la misma app de Meta y tokens separados: cada sistema guarda y renueva el suyo.

## 3. Requisitos funcionales

### 3.1 Conexión de la cuenta (Instagram Login)
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-01 | El agente expone un enlace «Conectar Instagram» que abre el consentimiento de Instagram Login con los tres permisos | Debe | Dado el enlace, cuando el dueño de la cuenta acepta, entonces vuelve al callback del agente y ve «Cuenta @usuario conectada» |
| RF-02 | El callback cambia el código por un token de larga duración (60 días) y lo guarda cifrado fuera de git, junto con el ID de la cuenta | Debe | Tras conectar, la base tiene el ID de la cuenta y el token; el `.env` no cambia y el token no aparece en los logs |
| RF-03 | El token se renueva solo antes de vencer | Debe | Con un token a menos de 10 días de vencer, el siguiente ciclo de renovación lo reemplaza y registra la nueva fecha; si falla, avisa al equipo |
| RF-04 | El callback valida `state` contra un valor firmado para evitar CSRF | Debe | Un callback con `state` alterado responde 400 y no guarda nada |

### 3.2 Comentarios y respuesta privada
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-05 | El agente recibe el webhook de Instagram del campo `comments` y valida su firma (`X-Hub-Signature-256` con el secreto de la app de Instagram) | Debe | Un webhook con firma válida se procesa; uno sin firma o con firma inválida responde 403 y no hace nada |
| RF-06 | Las reglas se configuran por agente en un archivo (palabras clave → mensaje del DM → respuesta pública opcional → publicaciones a las que aplica: todas o una lista) | Debe | Cambiar el archivo y reiniciar el agente cambia el comportamiento sin tocar código |
| RF-07 | La palabra clave coincide sin distinguir mayúsculas ni tildes, como palabra completa | Debe | «info», «INFO» e «Info!» coinciden con la regla «INFO»; «información» no, salvo que sea otra regla |
| RF-08 | Si coincide, envía una sola respuesta privada con el mensaje fijo de la regla | Debe | Un comentario con la palabra produce exactamente un DM; el mismo webhook repetido no manda otro |
| RF-09 | No responde comentarios de más de 7 días, de la propia cuenta ni respuestas a comentarios del propio negocio | Debe | Esos tres casos quedan registrados como «omitido» con su motivo, sin DM |
| RF-10 | Si la regla trae respuesta pública, responde al comentario con ese texto después de enviar el DM | Debería | Con respuesta pública configurada, el comentario muestra la respuesta de la cuenta; sin ella, no se publica nada |
| RF-11 | Cada comentario procesado queda registrado: comentario, publicación, usuario, regla, resultado (enviado / omitido / error) y fecha | Debe | Tras una prueba, la tabla tiene una fila por comentario con su resultado |
| RF-12 | Respeta el límite de 750 respuestas privadas por hora: si se acerca, encola y avisa al equipo | Debería | Con el límite simulado, el comentario 751 queda en cola y hay un aviso al equipo |

### 3.3 Conversación posterior
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-13 | Si la persona responde el DM, el mensaje entra al agente como cualquier conversación (memoria, herramientas, derivar a humano) | Debe | Una respuesta al DM recibe contestación del agente y queda en su historial |
| RF-14 | El agente sabe de qué publicación y regla vino la conversación | Debería | El contexto del agente incluye la palabra clave y la publicación de origen |
| RF-15 | Cada DM enviado por una regla registra un lead con origen «instagram:comentario:{palabra}» y avisa al equipo | Debería | Tras la prueba, el lead aparece con ese origen y llega el aviso por el canal del equipo |
| RF-16 | No escribe fuera de la ventana de 24 h: si el agente intenta responder fuera de plazo, lo registra y no envía | Debe | Un mensaje simulado 25 h después del último del usuario no se envía y queda en el log |

### 3.4 Migración de los DMs actuales
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-17 | El proveedor `instagram` de AgentKit envía y recibe DMs por Instagram Login (`graph.instagram.com`) con el token de la cuenta conectada | Debe | Un DM entrante a Reflexcam recibe respuesta del agente sin token de página de Facebook |
| RF-18 | La vía de Facebook Login deja de ser necesaria; si un agente todavía la usa, sigue funcionando hasta migrarlo o se documenta el paso | Debería | Los agentes con `IG_ACCESS_TOKEN` de página siguen respondiendo, o el README explica cómo migrar |

### 3.5 Métricas por cuenta en NccHUB
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-22 | Desde la ficha de un cliente en NccHUB, un socio conecta la cuenta de Instagram del cliente con Instagram Login (`instagram_business_basic` + `instagram_business_manage_insights`) | Debe | Tras aceptar el consentimiento, la ficha muestra «@usuario conectada» con la fecha |
| RF-23 | El token de NccHUB se guarda cifrado en Supabase, con RLS (solo socios del emisor dueño del cliente), y se renueva solo antes de vencer | Debe | Un usuario sin permiso no lo lee (prueba RLS); con menos de 10 días de vigencia se renueva; si falla, aviso al socio |
| RF-24 | La vista de métricas muestra, para los últimos 30 días: seguidores (actual y cambio), alcance, vistas, interacciones totales y un gráfico diario | Debe | Con la cuenta de Reflexcam, los números coinciden con los de Instagram (Estadísticas) con una diferencia máxima del 5 % o la del retraso propio de Meta |
| RF-25 | Lista de las 10 mejores publicaciones del periodo por interacciones, con miniatura, fecha, alcance, me gusta, comentarios, guardados y compartidos | Debe | La lista se ordena bien y cada publicación enlaza a Instagram |
| RF-26 | Selector de periodo: 7, 30 y 90 días | Debería | Cambiar el periodo recalcula los totales y el gráfico |
| RF-27 | Las métricas se guardan como foto diaria para no llamar a Meta en cada visita y para tener historia | Debería | Una segunda visita el mismo día no llama a la API; la tabla tiene una fila por cuenta y día |
| RF-28 | Desconectar la cuenta borra el token y deja de actualizar; la historia guardada se conserva hasta que el socio la borre | Debe | Tras desconectar, no hay token en la base y la ficha dice «No conectada» |

### 3.6 Material para el App Review
| ID | Requisito | Prioridad | Criterio de aceptación |
|---|---|---|---|
| RF-19 | Un video por permiso: `instagram_business_basic` (conectar y ver la cuenta), `instagram_business_manage_comments` (comentario → respuesta pública), `instagram_business_manage_messages` (DM y conversación) e `instagram_business_manage_insights` (métricas en NccHUB) | Debe | Cuatro videos en inglés o con subtítulos, de menos de 3 minutos, grabados con Reflexcam, que muestran la interfaz de Meta y el resultado en Instagram |
| RF-20 | Texto de uso por permiso («cómo lo usa la app y por qué lo necesita») e instrucciones paso a paso para el revisor | Debe | Documento `docs/app-review-instagram.md` listo para copiar al formulario |
| RF-21 | La política de privacidad menciona los datos de Instagram que se guardan y cómo se borran | Debe | ncchub.dev/privacidad cita Instagram, los datos guardados y la ruta de eliminación |

## 4. Requisitos de interfaz

**4.1 Usuario.** En AgentKit no hay panel en la v1. En NccHUB hay un botón de conexión en la ficha del cliente y una pestaña «Instagram» con las métricas (mismo diseño del resto del CRM, tema claro y oscuro, 390 y 1440). Las páginas del agente son dos HTML simples:

- «Conectar Instagram»;
- «Cuenta conectada» o «Error».

Deben verse bien en 390 px y en 1440 px, en español y con el nombre del negocio. Las reglas viven en un archivo del agente (p. ej. `config/instagram.yaml`).

**4.2 Interfaces externas.**

- **Graph API de Instagram** (`graph.instagram.com`):
  - OAuth: autorización, cambio de código por token, token de larga duración y renovación;
  - `POST /{ig-id}/messages` con `recipient.comment_id` para la respuesta privada y con `recipient.id` para los DMs;
  - `POST /{comment-id}/replies` para la respuesta pública;
  - suscripción de la cuenta a los webhooks `comments` y `messages`;
  - métricas de la cuenta y de cada publicación (`/{ig-id}/insights`, `/{media-id}/insights`), con los nombres de métrica vigentes al construir (Meta retiró algunas, como `impressions`, en favor de `views`).
- **Webhooks entrantes:** `GET` de verificación con `hub.challenge` y `POST` firmado.
- Las versiones exactas de la API se fijan al construir, contra la documentación vigente.

## 5. Requisitos no funcionales
| ID | Tipo | Requisito | Medida |
|---|---|---|---|
| RNF-01 | Rendimiento | El DM sale poco después del comentario | p95 < 10 s desde que llega el webhook hasta que Meta acepta el DM |
| RNF-02 | Seguridad | Firma del webhook obligatoria, `state` firmado en OAuth, tokens cifrados y fuera de git y de los logs | Revisión de código y pruebas de firma inválida y `state` alterado |
| RNF-03 | Seguridad | El texto del comentario pasa por la misma defensa contra inyección que los mensajes (envuelto, nunca como instrucción) | `tests/ataques_prompt.py` con un comentario malicioso: sin fugas |
| RNF-04 | Idempotencia | Meta puede repetir webhooks: nunca dos DMs por el mismo comentario | Prueba con el mismo webhook enviado 3 veces: 1 DM |
| RNF-05 | Disponibilidad | Si Meta falla, reintenta con espera y sin pasarse del plazo de 7 días | Error simulado: reintento registrado; tras 3 fallos, aviso al equipo |
| RNF-06 | Costos | El DM fijo no llama al modelo de IA; solo la conversación posterior | `uso_api` sin llamadas LLM por los DMs fijos |
| RNF-07 | Privacidad | Solo se guardan el ID, el usuario, el texto del comentario y el resultado; se borran a los 12 meses o cuando el titular lo pide | Tarea de borrado probada; política publicada (RF-21) |
| RNF-08 | Observabilidad | `/estado` muestra la cuenta conectada, el vencimiento del token y los DMs de hoy (enviados, omitidos, errores) | JSON de `/estado` con esos campos |
| RNF-09 | Mantenibilidad | Pruebas del core para la coincidencia de palabras, la idempotencia, la ventana de 7 días, la firma y la ventana de 24 h, sin llamar a Meta | `python tests/test_core.py` pasa |
| RNF-10 | Rendimiento | La pestaña de métricas carga rápido desde la foto diaria | p95 < 1,5 s con la foto del día ya guardada |
| RNF-11 | Seguridad | Los tokens de NccHUB nunca llegan al navegador; las llamadas a Meta van desde el servidor | Revisión de código; la red del navegador no muestra tokens |

## 6. Datos

**6.1 Entidades.** Van en tablas, con cabecera y detalle, sin JSON empaquetado:

- **`ig_cuentas`:** ID de Instagram, usuario, token cifrado, vence_en y conectada_en.
- **`ig_comentarios`:** comment_id (único), media_id, ID y usuario de quien comenta, texto, regla, resultado, motivo y fechas.
- Los DMs y la conversación usan las tablas actuales de mensajes y leads, con el origen en el lead.
- **En NccHUB (Supabase):**
  - `instagram_conexiones`: cliente, ID de Instagram, usuario, token cifrado, vence_en, conectada_por y fechas.
  - `instagram_metricas_dia`: conexión, fecha, seguidores, alcance, vistas e interacciones. Es única por conexión y fecha.
  - `instagram_publicaciones_dia`: conexión, fecha, media_id, tipo, enlace, miniatura, alcance, me gusta, comentarios, guardados y compartidos.

**6.2 Datos sensibles.** Hay dos tipos:

- **Token de acceso:** es un secreto; va cifrado con una clave del `.env`.
- **Datos personales del comentarista (Ley 1581):** se usan solo para la finalidad de responder, y se informa en la política de privacidad.

**6.3 Retención y respaldo.**

- Los comentarios se guardan 12 meses (RNF-07).
- Los tokens se borran al desconectar.
- El respaldo es el mismo de la base del agente.

**6.4 Migración.** No hay datos que migrar. Los agentes con DMs por la vía de Facebook siguen como están hasta que se reconecten (RF-18).

## 7. Fuera de alcance y futuro

- **Panel para editar reglas** (en NccHUB o en el panel de agentes): en la v1 basta un archivo; el panel llega cuando haya 3 o más clientes con reglas.
- **Alta de clientes de un clic** con enlace público: llega después de la aprobación y de publicar la app.
- **Comentarios en vivo y menciones en historias:** otros permisos y otros casos; se revisan si un cliente lo pide.
- **Plantillas de DM con botones o tarjetas (generic template):** no cambian la aprobación; se agregan después.
- **Métricas de conversión** (comentario → DM → lead → venta): llegan después, con los datos de la tabla.
- **Métricas para el cliente final** (portal del cliente en NccHUB) y reportes mensuales automáticos: después de la v1, cuando los socios validen qué números importan.

## 8. Historial de cambios
| Versión | Fecha | Cambio | Quién aprobó |
|---|---|---|---|
| 1.0 | 2026-09-29 | Primera versión. Decisiones de Nicolas: cuenta Reflexcam, Instagram Login, mensaje fijo + agente, respuesta pública opcional | — |
| 1.1 | 2026-09-29 | Se agregan las métricas por cuenta en NccHUB (RF-22 a RF-28) y el permiso `instagram_business_manage_insights`; los 4 permisos van en una sola revisión | — |

## 9. Checklist de aceptación

- [ ] RF-01 Enlace «Conectar Instagram» con los tres permisos
- [ ] RF-02 Token de larga duración guardado y cifrado, fuera de git y de los logs
- [ ] RF-03 Renovación automática del token y aviso si falla
- [ ] RF-04 `state` firmado en el callback
- [ ] RF-05 Webhook `comments` con firma validada
- [ ] RF-06 Reglas por agente en un archivo
- [ ] RF-07 Coincidencia sin mayúsculas ni tildes, por palabra completa
- [ ] RF-08 Un solo DM por comentario
- [ ] RF-09 Omite comentarios de más de 7 días, los propios y las respuestas del negocio
- [ ] RF-11 Registro de cada comentario procesado
- [ ] RF-13 Conversación posterior con el agente
- [ ] RF-16 Nada fuera de la ventana de 24 h
- [ ] RF-17 DMs por Instagram Login
- [ ] RF-22 Conexión de Instagram desde la ficha del cliente en NccHUB
- [ ] RF-23 Token cifrado con RLS y renovación
- [ ] RF-24 Métricas de 30 días que coinciden con Instagram
- [ ] RF-25 Top 10 de publicaciones
- [ ] RF-28 Desconectar borra el token
- [ ] RF-19 Cuatro videos del App Review
- [ ] RF-20 Textos e instrucciones para el revisor
- [ ] RF-21 Política de privacidad con Instagram
- [ ] RNF-02 / RNF-03 / RNF-04 Seguridad, inyección e idempotencia probadas
- [ ] RNF-09 Pruebas del core en verde
- [ ] RNF-11 Tokens de NccHUB solo en el servidor
- [ ] Verificación visual de las páginas de conexión a 390 y 1440
- [ ] Documentación: README, CLAUDE.md y `.env.example` al día
- [ ] App publicada (modo Activo) y verificación de empresa confirmada antes de enviar
- [ ] Aprobación final de Nicolas (fecha)
