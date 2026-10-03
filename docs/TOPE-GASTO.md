# Tope de gasto por agente (core v0.8.7)

Decidido por Nicolas el 2026-10-02 (SEMANA.md): topes configurables por agente en el `.env` para que
un abuso de un día no se coma el margen y para cuidar el margen del mes.

## Qué cuenta
- Lo que pagamos nosotros por ese agente y queda en `uso_api`: Claude, voz (TTS) y transcripción (STT).
  El cobro de Meta no cuenta (lo paga el cliente).
- Solo los canales de mensajería (WhatsApp e Instagram). El chat web ya tiene su propio tope
  (`WEB_CHAT_TOPE_USD_DIA`) y no se suma aquí, para que un abuso en la web no apague WhatsApp.
- Día y mes en hora de Bogotá; se reinician solos.

## Variables (`.env`)
| Variable | Qué hace | Sin la variable |
|---|---|---|
| `TOPE_USD_DIA` | Tope diario en USD (rango decidido: 2-4; arranque 2 con Haiku, 3 con Sonnet) | Sin tope diario |
| `TOPE_USD_MES` | Tope mensual en USD (rango decidido: 20-50) | Sin tope mensual |
| `TOPE_MSG_DERIVAR` | Lo que recibe el cliente cuando se pasa el tope diario y el equipo SÍ recibió el aviso | «Gracias por escribirnos 🙏 En un momento {NOMBRE_HUMANO} te responde por este mismo chat.» |
| `TOPE_MSG_SIN_EQUIPO` | Lo que recibe si NO hay canal de avisos (`ADMIN_PHONE`/Telegram) o el aviso falló | «Gracias por escribirnos 🙏 Por hoy ya no puedo seguir la conversación; escríbenos mañana y te atendemos.» |

Sin las variables el agente funciona igual que antes (actualizar el core no cambia nada hasta que se
configuren).

## Comportamiento
| Situación | Qué pasa |
|---|---|
| Día ≥ 80 % del tope diario | Deja la voz: responde solo en texto (sigue transcribiendo notas de voz para entenderlas). Aviso al equipo una vez al día. |
| Día ≥ 100 % del tope diario | No llama a Claude: pausa esa conversación hasta la medianoche de Bogotá (o `PAUSA_MINUTOS`, lo que sea mayor), avisa al equipo con el número del cliente (como `derivar_a_humano`) y le manda al cliente `TOPE_MSG_DERIVAR`; si el aviso no llegó, le manda `TOPE_MSG_SIN_EQUIPO` en vez de prometerle un asesor. El equipo recibe además un aviso general una vez al día. Al día siguiente vuelve solo. El `ADMIN_PHONE` nunca queda derivado. |
| Mes ≥ tope mensual | Solo texto (sin voz) hasta fin de mes. Aviso al equipo una vez al mes. |

Interpretaciones tomadas (Nicolas puede cambiarlas):
1. El 80 % quita solo la voz de salida (la cara); la transcripción de entrada sigue (cuesta ~USD 0,003/min
   y sin ella el agente no entiende la nota de voz).
2. El tope mensual no deriva a humano: solo quita la voz («al pasarlo, solo texto»).
3. En `MODO_BORRADOR` el mensaje de derivación sale directo al cliente, sin pasar por la aprobación del
   admin (es un texto fijo); el admin sigue pudiendo aprobar borradores con el tope pasado.
4. Si el `ADMIN_PHONE` le escribe al bot con el tope diario pasado, el bot le sigue respondiendo con IA
   (no se pausa al equipo); es una fuga mínima del tope a cambio de no bloquear al dueño.

## Avisos
Una vez por umbral (80 % del día, 100 % del día, mes) por día o por mes, en memoria del proceso: si el
servicio se reinicia (o hay varios workers de uvicorn), el aviso puede repetirse. La derivación de cada
cliente sí avisa siempre (el equipo necesita saber a quién atender); dos mensajes seguidos del mismo
cliente no lo derivan dos veces. Un fallo del canal de avisos nunca deja al cliente sin respuesta.
**El tope diario necesita un canal de avisos** (`ADMIN_PHONE` o Telegram): sin él nadie se entera de las
derivaciones y el cliente solo recibe el «escríbenos mañana».

## Otros detalles
- Sin `TOPE_USD_MES` la consulta trae solo lo de hoy (no el mes entero en cada mensaje).
- La nota de voz se transcribe antes de revisar el tope: al 100 % se paga esa transcripción (~USD 0,003/min)
  y el texto queda guardado para el humano.
- Instagram: el humano debe contestar dentro de la ventana de 24 h del último mensaje del cliente (igual
  que con `derivar_a_humano`).

## Pendiente
- Fijar las cifras con la semana de `uso_api` de Cora (~2026-10-06) y ponerlas en el `.env` de cada agente.
- Sacar el tag `v0.8.7` y subir el `requirements.txt` de cada agente (con autorización de Nicolas).
