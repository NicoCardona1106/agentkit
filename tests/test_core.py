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


def test_instagram_parse():
    from agentkit.providers.instagram import ProveedorInstagram

    payload = {"entry": [{"messaging": [
        {"sender": {"id": "IG123"}, "message": {"mid": "m1", "text": "hola"}},
        {"sender": {"id": "IG123"}, "message": {"mid": "m2", "is_echo": True, "text": "eco"}},
        {"sender": {"id": "IG456"}, "message": {"mid": "m3", "attachments": [
            {"type": "audio", "payload": {"url": "https://cdn/audio.mp4"}}]}},
    ]}]}

    class FakeRequest:
        async def json(self):
            return payload

    msgs = asyncio.run(ProveedorInstagram().parsear_webhook(FakeRequest()))
    assert len(msgs) == 2  # el eco se descarta
    assert msgs[0].telefono == "IG123" and msgs[0].texto == "hola"
    assert msgs[1].audio_ref == "https://cdn/audio.mp4"


def test_pagos_seleccion():
    from agentkit import pagos

    for var in ("WOMPI_PRIVATE_KEY", "MP_ACCESS_TOKEN", "STRIPE_SECRET_KEY", "PAGOS_PROVIDER"):
        os.environ.pop(var, None)
    assert not pagos.pagos_configurados()
    os.environ["MP_ACCESS_TOKEN"] = "APP_USR-test"
    assert pagos.proveedor_pago() == "mercadopago"
    os.environ["PAGOS_PROVIDER"] = "stripe"
    assert pagos.proveedor_pago() == "stripe"  # el override gana
    for var in ("MP_ACCESS_TOKEN", "PAGOS_PROVIDER"):
        os.environ.pop(var, None)


def test_voz_config():
    from agentkit import voz

    for var in ("GROQ_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(var, None)
    assert not voz.voz_configurada()
    os.environ["OPENAI_API_KEY"] = "sk-test"
    assert "openai.com" in voz._config()[0]
    os.environ["GROQ_API_KEY"] = "gsk-test"
    assert "groq.com" in voz._config()[0]  # Groq (gratis) tiene prioridad
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(var, None)


def test_tts():
    from agentkit import voz

    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    assert not voz.tts_configurada()
    os.environ["GEMINI_API_KEY"] = "AIza-test"
    assert voz.tts_configurada()
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ["OPENAI_API_KEY"] = "sk-test"
    assert voz.tts_configurada()
    os.environ.pop("OPENAI_API_KEY", None)

    hablado = voz.texto_para_voz("*Plan Pro*: $99.000/mes.\n\nPaga aquí: https://wompi.co/l/abc123")
    assert "http" not in hablado and "*" not in hablado and "\n" not in hablado
    assert "link" in hablado  # la URL se reemplaza por una mención al chat


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

    await memory.pausar_conversacion(tel, minutos=0)  # limpia pausas de corridas anteriores
    assert not await memory.conversacion_pausada(tel)
    await memory.pausar_conversacion(tel, minutos=5)
    assert await memory.conversacion_pausada(tel)

    lead_id = await memory.crear_lead(tel, "Andrés", "RTX 4070")
    ticket_id = await memory.crear_ticket(tel, "PC no enciende")
    assert lead_id >= 1 and ticket_id >= 1
    resumen = await memory.resumen_dia()
    assert resumen["conversaciones"] >= 1 and len(resumen["leads"]) >= 1


async def _test_borrador():
    from agentkit import borrador, memory

    os.environ["MODO_BORRADOR"] = "true"
    os.environ["ADMIN_PHONE"] = "whatsapp:+57 300 1112233"
    assert borrador.activo()
    assert borrador.es_admin("573001112233") and not borrador.es_admin("573009999999")

    enviados = []

    class FakeProv:
        async def enviar_mensaje(self, tel, texto):
            enviados.append((tel, texto))
            return True

    bid = await memory.crear_borrador("57311", "Hola, ¿en qué te ayudo?")
    r = await memory.resolver_borrador(bid, "enviado")
    assert r and r["telefono"] == "57311"
    assert await memory.resolver_borrador(bid, "enviado") is None  # no se envía dos veces

    await borrador.comando_admin(FakeProv(), "ok 999999")
    assert "no existe" in enviados[-1][1]
    bid2 = await memory.crear_borrador("57322", "Vale $10.000")
    await borrador.comando_admin(FakeProv(), f"editar {bid2} Vale $12.000")
    assert any(t == "57322" and "12.000" in x for t, x in enviados)
    await borrador.comando_admin(FakeProv(), "hola")  # sin comando → ayuda + pendientes
    assert "Pendientes" in enviados[-1][1]

    for var in ("MODO_BORRADOR", "ADMIN_PHONE"):
        os.environ.pop(var, None)


def test_webhook_verificacion():
    """GET /webhook: devuelve el challenge tal cual (aunque no sea numérico) y 403 con token malo."""
    from fastapi.testclient import TestClient
    os.environ["PROVIDER"] = "meta"
    os.environ["META_VERIFY_TOKEN"] = "tok-prueba"
    from agentkit.providers.meta import ProveedorMeta
    import agentkit.main as main_mod
    main_mod.proveedor = ProveedorMeta()
    c = TestClient(main_mod.app)
    r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok-prueba", "hub.challenge": "abc-123"})
    assert r.status_code == 200 and r.text == "abc-123", (r.status_code, r.text)
    r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "malo", "hub.challenge": "1"})
    assert r.status_code == 403, r.status_code
    assert c.get("/webhook").status_code == 200  # sin hub.mode sigue siendo un health check


async def _test_system_prompt_cacheable():
    """El system va en 2 bloques: el del negocio con cache_control y el contexto variable aparte."""
    from agentkit import brain, memory
    await memory.inicializar_db()
    bloques = await brain._system_prompt("57300000000")
    assert isinstance(bloques, list) and len(bloques) == 2
    assert bloques[0].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in bloques[1] and "Fecha y hora" in bloques[1]["text"]


async def _test_estado():
    """GET /estado: diffs exactos entre un llamado base y uno tras insertar datos frescos
    (la BD temporal no se limpia entre corridas, así que comparar contra un base es lo único
    que demuestra algo). Un mensaje de hace 25h no debe entrar en la ventana de 24h."""
    import logging
    import secrets as secrets_mod
    from datetime import datetime, timedelta

    from fastapi.testclient import TestClient

    from agentkit import memory
    from agentkit.memory import Mensaje, async_session
    import agentkit.main as main_mod

    await memory.inicializar_db()

    os.environ["REPORTE_TOKEN"] = "token-prueba"
    main_mod._iniciado = main_mod.datetime.utcnow()
    main_mod._arranque_monotonic = main_mod.time.monotonic()
    c = TestClient(main_mod.app)

    assert c.get("/estado").status_code == 403  # sin token
    assert c.get("/estado", params={"token": "malo"}).status_code == 403  # token incorrecto
    assert c.get("/estado", headers={"X-Reporte-Token": "malo"}).status_code == 403

    base = c.get("/estado", params={"token": "token-prueba"}).json()

    tel = f"test-estado-{secrets_mod.token_hex(4)}"  # teléfono nuevo: garantiza +1 conversación exacto
    await memory.guardar_mensaje(tel, "user", "hola, secreto de prueba")
    await memory.guardar_mensaje(tel, "assistant", "¡hola!")
    async with async_session() as session:  # mensaje fuera de la ventana de 24h: no debe contar
        session.add(Mensaje(telefono=tel, role="user", content="viejo",
                             timestamp=datetime.utcnow() - timedelta(hours=25)))
        await session.commit()
    await memory.crear_lead(tel, "Andrés", "RTX 4070")
    await memory.crear_ticket(tel, "PC no enciende")
    logging.getLogger("agentkit").error("error de prueba para /estado")

    r = c.get("/estado", headers={"X-Reporte-Token": "token-prueba"})  # cabecera también sirve
    assert r.status_code == 200, r.text
    data = r.json()
    claves = {"service", "version", "nombre", "proveedor", "modelo", "uptime_s", "iniciado",
              "modo_borrador", "ultimas_24h", "tickets_abiertos", "ultimo_mensaje",
              "borradores_pendientes", "errores_24h"}
    assert claves <= set(data.keys()), data.keys()
    assert data["service"] == "agentkit"
    assert isinstance(data["uptime_s"], float)

    b, u = base["ultimas_24h"], data["ultimas_24h"]
    assert u["mensajes_entrantes"] == b["mensajes_entrantes"] + 1, (u, b)  # no el de 25h atrás
    assert u["mensajes_salientes"] == b["mensajes_salientes"] + 1, (u, b)
    assert u["conversaciones"] == b["conversaciones"] + 1, (u, b)
    assert u["leads"] == b["leads"] + 1, (u, b)
    assert u["tickets"] == b["tickets"] + 1, (u, b)
    assert data["errores_24h"] == base["errores_24h"] + 1, (data["errores_24h"], base["errores_24h"])
    assert data["ultimo_mensaje"] and "T" in data["ultimo_mensaje"]  # ISO

    assert tel not in str(data) and "secreto de prueba" not in str(data)
    assert "Andrés" not in str(data) and "PC no enciende" not in str(data)

    os.environ.pop("REPORTE_TOKEN", None)


if __name__ == "__main__":
    test_humanizar()
    test_firma_twilio()
    test_firma_meta()
    test_instagram_parse()
    test_pagos_seleccion()
    test_voz_config()
    test_tts()
    test_herramientas_esquemas()
    asyncio.run(_test_memory())
    asyncio.run(_test_borrador())
    test_webhook_verificacion()
    asyncio.run(_test_system_prompt_cacheable())
    asyncio.run(_test_estado())
    print("OK — todos los self-checks pasaron")
