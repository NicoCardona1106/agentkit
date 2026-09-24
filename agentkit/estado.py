# agentkit/estado.py — Soporte para GET /estado: contador de errores y nombre del bot

import logging
import os
from collections import deque
from datetime import datetime, timedelta

import yaml

VENTANA_ERRORES = timedelta(hours=24)


class ContadorErrores(logging.Handler):
    """Cuenta logs de nivel ERROR (o mayor) del logger "agentkit" y sus hijos, por proceso,
    en las últimas 24h (otros loggers como uvicorn.error no entran: solo se engancha a "agentkit").

    Se poda al consultar, no con un timer — el volumen de errores de un agente
    de WhatsApp es bajo, no justifica un scheduler aparte.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        # ponytail: tope 10_000, se satura en tormenta de errores — pasar a métrica externa si eso pasa seguido
        self._timestamps: deque[datetime] = deque(maxlen=10_000)

    def emit(self, record: logging.LogRecord):
        self._timestamps.append(datetime.utcfromtimestamp(record.created))
        self.contar_24h()  # poda en caliente para no acumular de más entre consultas

    def contar_24h(self) -> int:
        limite = datetime.utcnow() - VENTANA_ERRORES
        while self._timestamps and self._timestamps[0] < limite:
            self._timestamps.popleft()
        return len(self._timestamps)


contador_errores = ContadorErrores()


def nombre_bot() -> str | None:
    """Nombre del agente: NOMBRE_BOT en el .env, o agente.nombre en config/business.yaml.
    Tolera un YAML mal formado (raíz que no es dict, agente que no es dict) sin reventar."""
    nombre = os.getenv("NOMBRE_BOT")
    if nombre:
        return nombre
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f) or {}
        agente = datos.get("agente") if isinstance(datos, dict) else None
        nombre = agente.get("nombre") if isinstance(agente, dict) else None
        return str(nombre) if nombre else None
    except (OSError, yaml.YAMLError):
        return None
