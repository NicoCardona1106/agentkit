# agentkit/estado.py — Soporte para GET /estado: contador de errores y nombre del bot

import logging
import os
from collections import deque
from datetime import datetime, timedelta

import yaml

VENTANA_ERRORES = timedelta(hours=24)


class ContadorErrores(logging.Handler):
    """Cuenta logs de nivel ERROR (o mayor) del logger "agentkit" en las últimas 24h.

    Se poda al consultar, no con un timer — el volumen de errores de un agente
    de WhatsApp es bajo, no justifica un scheduler aparte.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self._timestamps: deque[datetime] = deque()

    def emit(self, record: logging.LogRecord):
        self._timestamps.append(datetime.utcnow())

    def contar_24h(self) -> int:
        limite = datetime.utcnow() - VENTANA_ERRORES
        while self._timestamps and self._timestamps[0] < limite:
            self._timestamps.popleft()
        return len(self._timestamps)


contador_errores = ContadorErrores()


def nombre_bot() -> str | None:
    """Nombre del agente: NOMBRE_BOT en el .env, o agente.nombre en config/business.yaml."""
    nombre = os.getenv("NOMBRE_BOT")
    if nombre:
        return nombre
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f) or {}
        return datos.get("agente", {}).get("nombre") or None
    except FileNotFoundError:
        return None
