# agentkit/privacidad.py — Datos personales fuera de los logs (Ley 1581; informe de seguridad 2026-10-03)

from urllib.parse import urlparse


def ocultar(telefono: str | None) -> str:
    """Teléfono (o id) para el log: solo los 4 últimos caracteres. «573001112233» → «…2233»;
    el chat web conserva el prefijo para saber el canal («web:…a1b2»)."""
    if not telefono:
        return "?"
    prefijo = "web:" if telefono.startswith("web:") else ""
    resto = telefono[len(prefijo):]
    return f"{prefijo}…{resto[-4:]}" if len(resto) > 4 else f"{prefijo}…"


def host_permitido(url: str, dominios: tuple[str, ...]) -> bool:
    """True si la URL es https y su host es uno de `dominios` o un subdominio de ellos."""
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    host = (partes.hostname or "").lower().rstrip(".")
    return partes.scheme == "https" and any(host == d or host.endswith("." + d) for d in dominios)
