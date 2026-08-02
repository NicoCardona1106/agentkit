# tests/test_core.py — Self-check del core sin red ni API keys
# Uso: python tests/test_core.py

import asyncio
import base64
import hashlib
import hmac
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# BD temporal para no tocar agentkit.db
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.gettempdir()}/agentkit_test.db"


def test_humanizar():
    from agentkit.humanizar import MAX_BURBUJAS, partir_en_burbujas, pausa_escritura

    assert partir_en_burbujas("hola") == ["hola"]
    burbujas = partir_en_burbujas("Primer párrafo con suficiente texto para no unirse." * 3
                                  + "\n\n" + "Segundo párrafo también largo para quedar separado." * 3)
    assert len(burbujas) == 2
    muchas = partir_en_burbujas("\n\n".join(f"Párrafo número {i} " + "relleno " * 20 for i in range(8)))
    assert len(muchas) <= MAX_BURBUJAS
    assert "".join(muchas).count("Párrafo número") == 8  # no se pierde contenido
    assert 0 < pausa_escritura("hola " * 100) <= 3.0


def test_firma_twilio():
    from agentkit.providers.twilio import firma_twilio

    # Vector calculado con el algoritmo documentado por Twilio (HMAC-SHA1 de url+params ordenados)
    token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675309"}
    esperada = base64.b64encode(hmac.new(
        token.encode(),
        (url + "CallSid" + "CA1234567890ABCDE" + "Caller" + "+14158675309").encode(),
        hashlib.sha1).digest()).decode()
    assert firma_twilio(token, url, params) == esperada


def test_firma_meta():
    from agentkit.providers.meta import ProveedorMeta

    os.environ["META_APP_SECRET"] = "secreto"
    p = ProveedorMeta()
    cuerpo = b'{"entry": []}'
    firma_ok = "sha256=" + hmac.new(b"secreto", cuerpo, hashlib.sha256).hexdigest()

    class FakeRequest:
        headers = {"X-Hub-Signature-256": firma_ok}
        async def body(self):
            return cuerpo

    assert asyncio.run(p.validar_firma(FakeRequest())) is True
    FakeRequest.headers = {"X-Hub-Signature-256": "sha256=malo"}
    assert asyncio.run(p.validar_firma(FakeRequest())) is False


def test_herramientas_esquemas():
    from agentkit.herramientas import ESQUEMAS_BASE

    nombres = {e["name"] for e in ESQUEMAS_BASE}
    assert {"buscar_conocimiento", "registrar_lead", "crear_ticket",
            "recordar_cliente", "derivar_a_humano"} <= nombres
    for e in ESQUEMAS_BASE:
        assert e["input_schema"]["type"] == "object"


async def _test_memory():
    from agentkit import memory

    await memory.inicializar_db()
    tel = "test-570000000"
    await memory.limpiar_historial(tel)
    await memory.guardar_mensaje(tel, "user", "hola")
    await memory.guardar_mensaje(tel, "assistant", "¡hola!")
    historial = await memory.obtener_historial(tel)
    assert [m["role"] for m in historial] == ["user", "assistant"]

    await memory.guardar_dato_cliente(tel, nombre="Andrés", nota="le interesa una RTX")
    cliente = await memory.obtener_cliente(tel)
    assert cliente["nombre"] == "Andrés" and "RTX" in cliente["notas"]

    assert not await memory.conversacion_pausada(tel)
    await memory.pausar_conversacion(tel, minutos=5)
    assert await memory.conversacion_pausada(tel)

    lead_id = await memory.crear_lead(tel, "Andrés", "RTX 4070")
    ticket_id = await memory.crear_ticket(tel, "PC no enciende")
    assert lead_id >= 1 and ticket_id >= 1
    resumen = await memory.resumen_dia()
    assert resumen["conversaciones"] >= 1 and len(resumen["leads"]) >= 1


if __name__ == "__main__":
    test_humanizar()
    test_firma_twilio()
    test_firma_meta()
    test_herramientas_esquemas()
    asyncio.run(_test_memory())
    print("OK — todos los self-checks pasaron")
