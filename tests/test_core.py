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
    """STT: OpenAI gpt-4o-mini-transcribe si hay key; Groq si se fuerza o si no hay key de OpenAI."""
    from agentkit import voz

    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "STT_PROVEEDOR", "VOZ_MODELO"):
        os.environ.pop(var, None)
    assert not voz.voz_configurada()
    os.environ["GROQ_API_KEY"] = "gsk-test"
    assert voz._config()[0] == "groq" and "groq.com" in voz._config()[1]  # sin key de OpenAI
    os.environ["OPENAI_API_KEY"] = "sk-test"
    proveedor, url, _, modelo = voz._config()
    assert proveedor == "openai" and "openai.com" in url and modelo == "gpt-4o-mini-transcribe"
    os.environ["STT_PROVEEDOR"] = "groq"
    assert voz._config()[0] == "groq"  # forzado
    os.environ.pop("GROQ_API_KEY")
    assert voz._config() is None  # forzado sin su key: no cae a otro proveedor
    for var in ("OPENAI_API_KEY", "STT_PROVEEDOR"):
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

    # Selección de proveedor TTS por env
    os.environ.pop("TTS_PROVEEDOR", None)
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["GEMINI_API_KEY"] = "AIza-test"
    assert voz._elegir(voz._TTS, "TTS_PROVEEDOR") == "openai-audio"  # default: voz O3 (prueba de oído)
    assert voz._cadena_tts() == ["openai-audio", "openai", "gemini"]  # y sus respaldos
    os.environ["TTS_PROVEEDOR"] = "openai"
    assert voz._elegir(voz._TTS, "TTS_PROVEEDOR") == "openai"
    assert voz._cadena_tts() == ["openai", "gemini"]  # gpt-audio nunca es respaldo
    os.environ.pop("TTS_PROVEEDOR")
    os.environ.pop("GEMINI_API_KEY")
    assert voz._cadena_tts() == ["openai-audio", "openai"]  # sin key de Gemini
    os.environ["GEMINI_API_KEY"] = "AIza-test"
    os.environ["TTS_PROVEEDOR"] = "gemini"
    assert voz._elegir(voz._TTS, "TTS_PROVEEDOR") == "gemini"
    assert voz._cadena_tts() == ["gemini", "openai"]
    os.environ["TTS_PROVEEDOR"] = "elevenlabs"  # aún no implementado: sin voz, no otro proveedor
    assert not voz.tts_configurada()
    os.environ["TTS_PROVEEDOR"] = "gemini"
    os.environ.pop("GEMINI_API_KEY")
    assert not voz.tts_configurada()  # forzado sin su key
    for var in ("OPENAI_API_KEY", "TTS_PROVEEDOR"):
        os.environ.pop(var, None)

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


def test_precios_decimal():
    """Costo con Decimal: LLM con caché, audio por minuto, mínimo de Groq y override por JSON."""
    import json
    from decimal import Decimal

    from agentkit import precios

    os.environ["PRECIOS_ARCHIVO"] = os.path.join(tempfile.gettempdir(), "agentkit_precios_no_existe.json")
    # Haiku 4.5: 1000 in x 1 + 100 out x 5 + 2000 caché leída x 0.10 + 500 caché escrita x 1.25 (USD/M)
    usd = precios.costo_llm("claude-haiku-4-5", 1000, 100, 2000, 500)
    assert isinstance(usd, Decimal) and usd == Decimal("0.002325"), usd
    assert precios.costo_llm("claude-haiku-4-5-20251001", 1000, 100, 2000, 500) == usd  # ID con fecha
    assert precios.costo_llm("claude-sonnet-5", 1_000_000, 0) == Decimal("2")
    assert precios.costo_llm("modelo-desconocido", 1000, 1000) == Decimal(0)

    assert precios.costo_audio("gpt-4o-mini-transcribe", Decimal(30)) == Decimal("0.0015")
    assert precios.costo_audio("gpt-4o-mini-tts", Decimal(60)) == Decimal("0.015")
    # Groq whisper-large-v3: USD 0.111/hora con mínimo facturado de 10 s
    assert precios.costo_audio("whisper-large-v3", Decimal(3)) == Decimal("0.111") / 60 * 10 / 60

    ruta = os.path.join(tempfile.gettempdir(), "agentkit_precios_test.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"claude-haiku-4-5": {"salida": 4.5}, "modelo-nuevo": {"minuto": "0.01"}}, f)
    os.environ["PRECIOS_ARCHIVO"] = ruta
    try:
        assert precios.costo_llm("claude-haiku-4-5", 0, 1_000_000) == Decimal("4.5")
        assert precios.costo_llm("claude-haiku-4-5", 1_000_000, 0) == Decimal("1")  # lo demás sigue
        assert precios.costo_audio("modelo-nuevo", Decimal(120)) == Decimal("0.02")
    finally:
        os.environ.pop("PRECIOS_ARCHIVO")
        os.remove(ruta)


class _Captura:
    """Captura los logs del logger "agentkit" de nivel >= `nivel` mientras dura el bloque with."""
    def __init__(self, nivel):
        import logging
        self.handler = logging.Handler(nivel)
        self.handler.emit = lambda r: self.registros.append(r.getMessage())
        self.registros = []

    def __enter__(self):
        import logging
        logging.getLogger("agentkit").addHandler(self.handler)
        return self.registros

    def __exit__(self, *exc):
        import logging
        logging.getLogger("agentkit").removeHandler(self.handler)


def test_precios_modelos_claude_y_json_malo():
    """Sonnet 4.x / Opus 4.x-5.x con precio (el prefijo más largo gana) y un precios.json roto
    se loguea y deja la tabla interna; usd se guarda con 10 decimales fijos."""
    import logging
    from decimal import Decimal

    from agentkit import precios

    M = 1_000_000
    assert precios.costo_llm("claude-sonnet-4-5-20250929", M, 0) == Decimal("3")
    assert precios.costo_llm("claude-sonnet-4-20250514", 0, M) == Decimal("15")
    assert precios.costo_llm("claude-opus-4-1-20250805", M, 0) == Decimal("15")
    assert precios.costo_llm("claude-opus-4-5-20251101", M, 0) == Decimal("5")
    assert precios.costo_llm("claude-opus-4-8", 0, 0, M, 0) == Decimal("0.50")
    assert precios.costo_llm("claude-opus-5", 0, M) == Decimal("25")
    assert precios.costo_llm("claude-opus-5-5", M, 0, 0, M) == Decimal("9")  # 4 entrada + 5 escritura
    assert precios.tiene_precio("claude-haiku-4-5") and not precios.tiene_precio("modelo-raro")

    ruta = os.path.join(tempfile.gettempdir(), "agentkit_precios_roto.json")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("{esto no es json")
    os.environ["PRECIOS_ARCHIVO"] = ruta
    try:
        with _Captura(logging.ERROR) as errores:
            assert precios.costo_llm("claude-haiku-4-5", M, 0) == Decimal("1")  # tabla interna
            assert precios.costo_llm("claude-haiku-4-5", M, 0) == Decimal("1")
        assert len(errores) == 1 and "inválido" in errores[0]  # leído una vez (caché por mtime)
    finally:
        os.environ.pop("PRECIOS_ARCHIVO")
        os.remove(ruta)

    filas = []

    async def capturar(**campos):
        filas.append(campos)

    class Uso:
        input_tokens, output_tokens = 1, 0

    from agentkit import memory
    registrar_real = memory.registrar_uso
    memory.registrar_uso = capturar
    try:
        asyncio.run(precios.registrar("llm", "anthropic", "claude-haiku-4-5", usage=Uso()))
    finally:
        memory.registrar_uso = registrar_real
    assert filas[0]["usd"] == "0.0000010000", filas  # nunca "1E-6"


def test_voz_valores_de_otro_proveedor():
    """Un .env viejo (Groq/Gemini) sigue funcionando con OpenAI: cada proveedor ignora modelo y
    voz ajenos (warning una sola vez) y usa su default; OPENAI_/GEMINI_TTS_VOZ ganan sobre TTS_VOZ."""
    import base64
    import json
    import logging

    import httpx

    from agentkit import memory, voz

    viejas = {"VOZ_MODELO": "whisper-large-v3", "TTS_MODELO": "gemini-2.5-flash-preview-tts",
              "TTS_VOZ": "Kore"}
    todas = ("OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "STT_PROVEEDOR", "TTS_PROVEEDOR",
             "VOZ_MODELO", "TTS_MODELO", "TTS_VOZ", "OPENAI_TTS_VOZ", "GEMINI_TTS_VOZ", "TTS_INSTRUCCIONES")
    for var in todas:
        os.environ.pop(var, None)
    os.environ.update(viejas)
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["TTS_PROVEEDOR"] = "openai"

    enviados = []

    def responder(request):
        enviados.append(request)
        if "googleapis" in str(request.url):
            pcm = base64.b64encode(b"pcm").decode()
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"data": pcm}}]}}]})
        return httpx.Response(200, content=b"mp3")

    async def pcm_falso(pcm):
        return b"mp3-gemini"

    async def no_registrar(**campos):
        pass

    cliente_real, registrar_real, pcm_real = httpx.AsyncClient, memory.registrar_uso, voz._pcm_a_mp3
    httpx.AsyncClient = lambda **kw: cliente_real(transport=httpx.MockTransport(responder), **kw)
    memory.registrar_uso, voz._pcm_a_mp3 = no_registrar, pcm_falso
    voz._avisados.clear()
    try:
        with _Captura(logging.WARNING) as avisos:
            assert voz._config()[3] == "gpt-4o-mini-transcribe"  # VOZ_MODELO de Groq ignorado
            assert voz._config()[3] == "gpt-4o-mini-transcribe"
            assert asyncio.run(voz.sintetizar("hola")) == b"mp3"
            assert asyncio.run(voz.sintetizar("hola")) == b"mp3"
        cuerpo = json.loads(enviados[-1].content)
        assert cuerpo["model"] == "gpt-4o-mini-tts" and cuerpo["voice"] == "marin"
        assert len(avisos) == 3, avisos  # VOZ_MODELO, TTS_MODELO y TTS_VOZ: una vez cada uno

        os.environ["OPENAI_TTS_VOZ"] = "coral"  # la específica gana sobre TTS_VOZ
        asyncio.run(voz.sintetizar("hola"))
        assert json.loads(enviados[-1].content)["voice"] == "coral"

        os.environ["STT_PROVEEDOR"] = "groq"  # Groq forzado con un modelo de OpenAI
        os.environ["GROQ_API_KEY"] = "gsk-test"
        os.environ["VOZ_MODELO"] = "gpt-4o-mini-transcribe"
        assert voz._config()[3] == "whisper-large-v3"

        # Respaldo Gemini con el .env de OpenAI (TTS_VOZ=marin, TTS_MODELO=gpt-4o-mini-tts)
        os.environ.pop("OPENAI_API_KEY")
        os.environ.pop("TTS_PROVEEDOR")
        os.environ.update({"GEMINI_API_KEY": "AIza-test", "TTS_VOZ": "marin", "TTS_MODELO": "gpt-4o-mini-tts"})
        assert asyncio.run(voz.sintetizar("hola")) == b"mp3-gemini"
        assert "gemini-2.5-flash-preview-tts" in str(enviados[-1].url)
        cuerpo = json.loads(enviados[-1].content)
        voz_gemini = cuerpo["generationConfig"]["speechConfig"]
        assert voz_gemini["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
        # Gemini no tiene campo instructions: el estilo va antepuesto, como en la prueba de oído
        assert cuerpo["contents"][0]["parts"][0]["text"] == f"{voz.INSTRUCCIONES_GEMINI}\n\nhola"
        os.environ["TTS_INSTRUCCIONES"] = "Habla como paisa"
        asyncio.run(voz.sintetizar("hola"))
        assert json.loads(enviados[-1].content)["contents"][0]["parts"][0]["text"] == "Habla como paisa\n\nhola"
        os.environ["TTS_MODELO"] = "gemini-3.8-flash-tts"  # lee el texto literal: sin prefijo
        asyncio.run(voz.sintetizar("hola"))
        assert json.loads(enviados[-1].content)["contents"][0]["parts"][0]["text"] == "hola"
        os.environ["TTS_MODELO"] = "gpt-4o-mini-tts"
        os.environ["GEMINI_TTS_VOZ"] = "Puck"
        asyncio.run(voz.sintetizar("hola"))
        voz_gemini = json.loads(enviados[-1].content)["generationConfig"]["speechConfig"]
        assert voz_gemini["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    finally:
        httpx.AsyncClient, memory.registrar_uso, voz._pcm_a_mp3 = cliente_real, registrar_real, pcm_real
        for var in todas:
            os.environ.pop(var, None)


def test_estado_costo_falla_no_rompe():
    """Si resumen_costos revienta, /estado responde igual con costo_usd null."""
    from fastapi.testclient import TestClient

    from agentkit import memory
    import agentkit.main as main_mod

    async def reventar():
        raise RuntimeError("BD caída")

    asyncio.run(memory.inicializar_db())
    real = memory.resumen_costos
    memory.resumen_costos = reventar
    os.environ["REPORTE_TOKEN"] = "token-prueba"
    try:
        r = TestClient(main_mod.app).get("/estado", headers={"X-Reporte-Token": "token-prueba"})
    finally:
        memory.resumen_costos = real
        os.environ.pop("REPORTE_TOKEN", None)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["costo_usd"] is None and "ultimas_24h" in data and "errores_24h" in data


def test_duracion_audio():
    """OGG/Opus: duración exacta del granule de la última página; otro formato: por tamaño."""
    from decimal import Decimal

    from agentkit import voz

    def pagina(granulo: int) -> bytes:
        return b"OggS" + bytes(2) + granulo.to_bytes(8, "little") + bytes(20)

    assert voz.duracion_audio(pagina(0) + pagina(48000 * 7)) == Decimal(7)
    assert voz.duracion_audio(bytes(4000)) == Decimal(2)  # estimado a 2.000 bytes/s


def test_modelo_default_haiku():
    import importlib

    from agentkit import brain

    previo = os.environ.pop("CLAUDE_MODEL", None)
    try:
        assert importlib.reload(brain).MODELO == "claude-haiku-4-5"
        os.environ["CLAUDE_MODEL"] = "claude-sonnet-5"
        assert importlib.reload(brain).MODELO == "claude-sonnet-5"  # override por env
    finally:
        os.environ.pop("CLAUDE_MODEL", None)
        if previo:
            os.environ["CLAUDE_MODEL"] = previo
        importlib.reload(brain)


class _Usage:
    input_tokens = 2000
    output_tokens = 40
    cache_read_input_tokens = 1000
    cache_creation_input_tokens = 0


class _FakeAnthropic:
    """Cliente falso: una sola respuesta de texto, sin herramientas."""
    class messages:
        @staticmethod
        async def create(**kwargs):
            from types import SimpleNamespace
            return SimpleNamespace(stop_reason="end_turn", usage=_Usage(),
                                   content=[SimpleNamespace(type="text", text="¡Hola! ¿En qué te ayudo?")])


def test_costo_llm_registrado_y_fallo_no_rompe():
    """brain registra una fila llm con el usage real; si el registro revienta, la respuesta sale igual."""
    from decimal import Decimal

    from agentkit import brain, memory, precios

    async def correr():
        await memory.inicializar_db()
        filas = []

        async def capturar(**campos):
            filas.append(campos)

        async def reventar(**campos):
            raise RuntimeError("BD caída")

        cliente_real, registrar_real = brain.client, memory.registrar_uso
        brain.client = _FakeAnthropic()
        try:
            memory.registrar_uso = capturar
            assert await brain.generar_respuesta("57300", "hola", [], None) == "¡Hola! ¿En qué te ayudo?"
            (fila,) = filas
            assert fila["tipo"] == "llm" and fila["modelo"] == brain.MODELO
            assert fila["tokens_entrada"] == 2000 and fila["tokens_cache_lectura"] == 1000
            assert Decimal(fila["usd"]) == precios.costo_llm(brain.MODELO, 2000, 40, 1000, 0)

            memory.registrar_uso = reventar
            assert await brain.generar_respuesta("57300", "hola", [], None) == "¡Hola! ¿En qué te ayudo?"
        finally:
            brain.client, memory.registrar_uso = cliente_real, registrar_real

    asyncio.run(correr())


def test_tts_openai_payload_y_costo():
    """OpenAI TTS manda voz + instructions (mp3) y registra una fila tts con los caracteres;
    un registro que falla no impide devolver el audio. Sin red: transporte falso de httpx."""
    import json

    import httpx

    from agentkit import memory, voz

    enviados = []

    def responder(request):
        enviados.append(request)
        return httpx.Response(200, content=b"ID3-mp3-falso")

    async def correr():
        await memory.inicializar_db()
        filas = []

        async def capturar(**campos):
            filas.append(campos)

        async def reventar(**campos):
            raise RuntimeError("BD caída")

        cliente_real, registrar_real = httpx.AsyncClient, memory.registrar_uso
        httpx.AsyncClient = lambda **kw: cliente_real(transport=httpx.MockTransport(responder), **kw)
        for var in ("TTS_PROVEEDOR", "TTS_MODELO", "TTS_VOZ", "TTS_INSTRUCCIONES", "GEMINI_API_KEY"):
            os.environ.pop(var, None)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["TTS_PROVEEDOR"] = "openai"
        try:
            memory.registrar_uso = capturar
            assert await voz.sintetizar("Hola, claro que sí") == b"ID3-mp3-falso"
            cuerpo = json.loads(enviados[-1].content)
            assert cuerpo["model"] == "gpt-4o-mini-tts" and cuerpo["voice"] == "marin"
            assert cuerpo["response_format"] == "mp3" and "Colombia" in cuerpo["instructions"]
            (fila,) = filas
            assert fila["tipo"] == "tts" and fila["caracteres"] == len("Hola, claro que sí")

            os.environ["TTS_INSTRUCCIONES"] = "Habla como paisa"
            memory.registrar_uso = reventar
            assert await voz.sintetizar("Hola") == b"ID3-mp3-falso"
            assert json.loads(enviados[-1].content)["instructions"] == "Habla como paisa"
        finally:
            httpx.AsyncClient, memory.registrar_uso = cliente_real, registrar_real
            for var in ("OPENAI_API_KEY", "TTS_INSTRUCCIONES", "TTS_PROVEEDOR"):
                os.environ.pop(var, None)

    asyncio.run(correr())


def test_estado_costo():
    """GET /estado agrega costo_usd {hoy, mes, desglose} en texto decimal, con días de Bogotá.
    Compara diffs contra una base (la BD temporal no se limpia entre corridas)."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from fastapi.testclient import TestClient

    from agentkit import memory
    import agentkit.main as main_mod

    async def insertar():
        ahora = datetime.utcnow()
        hoy_bogota = datetime.now(memory.BOGOTA).replace(hour=0, minute=0, second=0, microsecond=0)
        antes_de_hoy = hoy_bogota.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        base = dict(proveedor="x", modelo="claude-haiku-4-5")
        await memory.registrar_uso(tipo="llm", usd="0", creado_en=ahora, proveedor="x", modelo="modelo-sin-precio-x")
        await memory.registrar_uso(tipo="llm", usd="0.001", creado_en=ahora, **base)
        await memory.registrar_uso(tipo="stt", usd="0.0002", creado_en=ahora, **base)
        await memory.registrar_uso(tipo="tts", usd="0.0003", creado_en=ahora, **base)
        # 1 s antes de la medianoche de Bogotá: no es de hoy (aunque en UTC pueda serlo)
        await memory.registrar_uso(tipo="llm", usd="0.01", creado_en=antes_de_hoy, **base)
        await memory.registrar_uso(tipo="llm", usd="5", creado_en=ahora - timedelta(days=40), **base)
        return hoy_bogota.day != 1  # el de anoche entra al mes solo si hoy no es día 1

    asyncio.run(memory.inicializar_db())
    os.environ["REPORTE_TOKEN"] = "token-prueba"
    c = TestClient(main_mod.app)
    try:
        antes = c.get("/estado", headers={"X-Reporte-Token": "token-prueba"}).json()
        anoche_en_mes = asyncio.run(insertar())
        r = c.get("/estado", headers={"X-Reporte-Token": "token-prueba"})
        assert r.status_code == 200, r.text
        despues = r.json()
    finally:
        os.environ.pop("REPORTE_TOKEN", None)

    assert {"ultimas_24h", "errores_24h", "modelo", "version"} <= set(despues)  # campos previos intactos
    a, d = antes["costo_usd"], despues["costo_usd"]
    assert isinstance(d["hoy"], str) and isinstance(d["desglose"]["llm"], str)  # nunca float
    assert "modelo-sin-precio-x" in d["modelos_sin_precio"]
    assert "claude-haiku-4-5" not in d["modelos_sin_precio"]

    def diff(*ruta):
        x, y = a, d
        for k in ruta:
            x, y = x[k], y[k]
        return Decimal(y) - Decimal(x)

    extra = Decimal("0.01") if anoche_en_mes else Decimal(0)
    assert diff("hoy") == Decimal("0.0015"), (a, d)
    assert diff("mes") == Decimal("0.0015") + extra, (a, d)
    assert diff("desglose", "llm") == Decimal("0.001") + extra
    assert diff("desglose", "stt") == Decimal("0.0002")
    assert diff("desglose", "tts") == Decimal("0.0003")


# Mensaje system con el que se generó la muestra O3 (DECIR de herramientas/prueba-voces/ronda_openai_audio.py),
# copiado literal: si alguien toca las constantes de voz.py, esta prueba lo avisa.
DECIR_MUESTRA_O3 = (
    "Habla en español de Colombia, con tono cálido y cercano, como una persona amable que atiende por "
    "WhatsApp. Habla de corrido y con soltura: une las frases sin pausas largas, no te detengas en las comas "
    "ni entre oraciones, y mantén un ritmo conversacional ágil y continuo. Nada de locutor ni de robot."
    " Tu única tarea es decir en voz alta, palabra por palabra, el mensaje del usuario, "
    "como si se lo estuvieras diciendo a un cliente por nota de voz. No agregues ni quites nada.")

_USAGE_GPT_AUDIO = {"prompt_tokens": 120, "completion_tokens": 900,
                    "prompt_tokens_details": {"audio_tokens": 0, "cached_tokens": 0},
                    "completion_tokens_details": {"audio_tokens": 850}}


def test_es_fiel():
    """Guarda de fidelidad: la puntuación, tildes, `$` y puntos de miles no importan; un número
    distinto o un texto inventado no pasan."""
    from agentkit import voz

    pedido = "¡Claro que sí! La hora de carro está en $3.500 y el día completo en $20.000."
    assert voz.es_fiel(pedido, "Claro que si, la hora de carro esta en 3500 y el dia completo en 20000")
    assert not voz.es_fiel(pedido, "¡Claro que sí! La hora de carro está en $3.000 y el día completo en $20.000.")
    assert not voz.es_fiel(pedido, "Hola, ¿en qué te puedo ayudar hoy?")
    assert not voz.es_fiel("Tu placa es ABC123 y sales a las 5:30", "Tu placa es ABC124 y sales a las 5:30")
    assert not voz.es_fiel("Te espero a las 5:30", "Te espero a las 5 y 30 de la tarde")
    assert not voz.es_fiel(pedido, "")

    # Palabras críticas (revisión): la negación o el día cambiados no pasan aunque la similitud sea alta
    assert not voz.es_fiel("Uy qué pena, no tenemos cupo para hoy", "Uy qué pena, tenemos cupo para hoy")
    assert not voz.es_fiel("El parqueadero no está abierto a esa hora", "El parqueadero está abierto a esa hora")
    assert not voz.es_fiel("Te esperamos el lunes a las 8", "Te esperamos el martes a las 8")
    assert voz.es_fiel("Sí, claro que sí", "Si claro que si")
    # Límite conocido: un sustantivo cambiado en un texto largo (≥ 20 palabras, umbral 0,95) pasa
    largo = ("Claro que te ayudo con eso, la mensualidad para el carro incluye el lavado básico cada "
             "quince días y el parqueo cubierto en el segundo piso del edificio principal")
    assert voz.es_fiel(largo, largo.replace("carro", "moto"))

    # Normalización (revisión): a. m. / p. m. y separadores de miles
    assert voz._palabras("a las 5 p. m.") == voz._palabras("a las 5pm") == voz._palabras("a las 5 PM")
    assert voz._palabras("abre a.m.") == voz._palabras("abre am")
    for escrito in ("$30.000", "30,000", "30 000", "30\u00a0000"):
        assert voz._palabras(escrito) == ["30000"], escrito
    assert voz.es_fiel("Abrimos a las 6 a. m. y la hora vale $30.000", "Abrimos a las 6am y la hora vale 30 000")


def test_tts_gpt_audio_payload_guarda_y_costo():
    """Default openai-audio: payload de Chat Completions como la muestra O3, costo desde usage y
    caída al respaldo (gpt-4o-mini-tts) si el transcript no pasa la guarda, registrando las dos
    llamadas. Si todo el TTS falla, sintetizar devuelve None sin lanzar. Sin red."""
    import json
    import logging
    from decimal import Decimal

    import httpx

    from agentkit import memory, precios, voz

    texto = "Claro que sí. La hora de carro está en $3.500 y si te quedas todo el día te sale en $20.000."
    dicho = [texto]
    estado = {"http": 200}
    enviados = []

    def responder(request):
        enviados.append(request)
        if estado["http"] is None:
            raise httpx.ConnectError("sin red")
        if estado["http"] != 200:
            return httpx.Response(estado["http"], text="caído")
        if "chat/completions" in str(request.url):
            audio = {"data": base64.b64encode(b"mp3-o3").decode(), "transcript": dicho[0]}
            return httpx.Response(200, json={"choices": [{"message": {"audio": audio}}],
                                             "usage": _USAGE_GPT_AUDIO})
        return httpx.Response(200, content=b"mp3-respaldo")

    filas = []

    async def capturar(**campos):
        filas.append(campos)

    todas = ("OPENAI_API_KEY", "GEMINI_API_KEY", "TTS_PROVEEDOR", "TTS_MODELO", "OPENAI_AUDIO_MODELO",
             "TTS_VOZ", "OPENAI_TTS_VOZ", "TTS_INSTRUCCIONES")
    for var in todas:
        os.environ.pop(var, None)
    os.environ["OPENAI_API_KEY"] = "sk-test"
    cliente_real, registrar_real = httpx.AsyncClient, memory.registrar_uso
    httpx.AsyncClient = lambda **kw: cliente_real(transport=httpx.MockTransport(responder), **kw)
    memory.registrar_uso = capturar
    try:
        # 1) Fiel (distinta puntuación): sale el audio de gpt-audio y una fila con el costo exacto
        dicho[0] = "Claro que sí, la hora de carro está en 3.500 y si te quedas todo el día te sale en 20.000"
        assert asyncio.run(voz.sintetizar(texto)) == b"mp3-o3"
        assert str(enviados[-1].url) == "https://api.openai.com/v1/chat/completions"
        cuerpo = json.loads(enviados[-1].content)
        assert cuerpo == {"model": "gpt-audio-1.5", "modalities": ["text", "audio"],
                          "audio": {"voice": "marin", "format": "mp3"},
                          "messages": [{"role": "system", "content": DECIR_MUESTRA_O3},
                                       {"role": "user", "content": texto}]}, cuerpo
        (fila,) = filas
        assert fila["tipo"] == "tts" and fila["proveedor"] == "openai-audio" and fila["modelo"] == "gpt-audio-1.5"
        assert fila["tokens_entrada"] == 120 and fila["tokens_salida"] == 900
        # 120 texto in x 2.50 + 50 texto out x 10 + 850 audio out x 64 (USD por millón)
        assert fila["usd"] == "0.0552000000", fila["usd"]
        assert precios.costo_tokens_audio("gpt-audio-1.5", 120, 0, 50, 850) == Decimal("0.0552")

        # 2) Número cambiado y 3) texto inventado: se descarta, sale el respaldo y quedan 2 filas
        for malo in ("Claro que sí, la hora de carro está en $3.000 y si te quedas todo el día te sale en $20.000",
                     "¡Hola! Qué más, bienvenido. ¿En qué te puedo ayudar hoy?"):
            filas.clear()
            dicho[0] = malo
            with _Captura(logging.WARNING) as avisos:
                assert asyncio.run(voz.sintetizar(texto)) == b"mp3-respaldo"
            assert any("cambió el texto" in a for a in avisos), avisos
            assert "audio/speech" in str(enviados[-1].url)
            respaldo = json.loads(enviados[-1].content)
            assert respaldo["model"] == "gpt-4o-mini-tts" and respaldo["voice"] == "marin"
            assert respaldo["instructions"] == voz.INSTRUCCIONES_FLUIDO
            assert [f["proveedor"] for f in filas] == ["openai-audio", "openai"]
            assert filas[0]["usd"] == "0.0552000000"  # la llamada descartada también se cobra

        # Voz de gpt-4o-mini-tts que no está en VOCES_GPT_AUDIO: gpt-audio usa marin
        os.environ["OPENAI_TTS_VOZ"] = "nova"
        dicho[0] = texto
        assert asyncio.run(voz.sintetizar(texto)) == b"mp3-o3"
        assert json.loads(enviados[-1].content)["audio"]["voice"] == "marin"
        os.environ.pop("OPENAI_TTS_VOZ")

        # Modelo validado: uno que no es gpt-audio se ignora (default + aviso)
        os.environ["TTS_MODELO"] = "gpt-4o-mini-tts"
        dicho[0] = texto
        assert asyncio.run(voz.sintetizar(texto)) == b"mp3-o3"
        assert json.loads(enviados[-1].content)["model"] == "gpt-audio-1.5"
        os.environ.pop("TTS_MODELO")

        # 4) Todo el TTS caído (HTTP 500 y sin red), con Gemini de último respaldo: None, sin lanzar
        os.environ["GEMINI_API_KEY"] = "AIza-test"
        assert voz._cadena_tts() == ["openai-audio", "openai", "gemini"]
        for falla in (500, None):
            estado["http"] = falla
            n = len(enviados)
            assert asyncio.run(voz.sintetizar(texto)) is None
            assert len(enviados) - n == 3  # probó los tres
    finally:
        httpx.AsyncClient, memory.registrar_uso = cliente_real, registrar_real
        for var in todas:
            os.environ.pop(var, None)


async def _test_voz_fluida_solo_en_turnos_de_voz():
    """La instrucción de voz fluida va solo en turnos de voz y fuera del bloque cacheado; si el
    cliente habla y todo el TTS falla, la respuesta sale en texto igual."""
    import secrets as secrets_mod

    import httpx

    from agentkit import brain, memory, voz
    from agentkit.providers import MensajeEntrante
    import agentkit.main as main_mod

    await memory.inicializar_db()
    tel = f"test-voz-{secrets_mod.token_hex(4)}"
    texto_sin, texto_con = await brain._system_prompt(tel), await brain._system_prompt(tel, en_voz=True)
    assert texto_sin[0] == texto_con[0]  # bloque cacheado idéntico
    assert brain.INSTRUCCION_VOZ in texto_con[1]["text"] and brain.INSTRUCCION_VOZ not in texto_sin[1]["text"]

    llamadas, textos, audios = [], [], []

    async def generar(telefono, mensaje, historial, proveedor, en_voz=False):
        llamadas.append(en_voz)
        return "Claro que sí, la hora está en $3.500"

    async def transcribir(audio, nombre_archivo="audio.ogg"):
        return "cuánto vale la hora"

    class FakeProv:
        async def descargar_audio(self, ref):
            return b"OggS"

        async def enviar_mensaje(self, tel, texto):
            textos.append(texto)
            return True

        async def enviar_audio_url(self, tel, url):
            audios.append(url)
            return True

    def sin_red(request):
        raise httpx.ConnectError("sin red")

    reales = (brain.generar_respuesta, voz.transcribir, main_mod.proveedor, httpx.AsyncClient)
    cliente_real = httpx.AsyncClient
    brain.generar_respuesta, voz.transcribir, main_mod.proveedor = generar, transcribir, FakeProv()
    httpx.AsyncClient = lambda **kw: cliente_real(transport=httpx.MockTransport(sin_red), **kw)
    for var in ("MODO_BORRADOR", "TTS_PROVEEDOR", "GEMINI_API_KEY"):
        os.environ.pop(var, None)
    os.environ.update({"OPENAI_API_KEY": "sk-test", "PUBLIC_URL": "https://agente.test", "HUMANIZAR": "false"})
    try:
        await main_mod.procesar_mensaje(MensajeEntrante(telefono=tel, texto="hola", mensaje_id="t1"))
        await main_mod.procesar_mensaje(MensajeEntrante(telefono=tel, texto="", mensaje_id="t2", audio_ref="m1"))
    finally:
        brain.generar_respuesta, voz.transcribir, main_mod.proveedor, httpx.AsyncClient = reales
        for var in ("OPENAI_API_KEY", "PUBLIC_URL", "HUMANIZAR"):
            os.environ.pop(var, None)
    assert llamadas == [False, True]  # instrucción de voz solo en el turno de nota de voz
    assert audios == [] and textos == ["Claro que sí, la hora está en $3.500"] * 2  # TTS caído → texto

    # Voz colgada: al vencer VOZ_TIMEOUT_TOTAL sale el texto
    async def sintetizar_lento(texto):
        await asyncio.sleep(5)
        return b"tarde"

    textos.clear()
    reales_voz = (brain.generar_respuesta, voz.transcribir, main_mod.proveedor, voz.sintetizar,
                  main_mod.VOZ_TIMEOUT_TOTAL)
    brain.generar_respuesta, voz.transcribir, main_mod.proveedor = generar, transcribir, FakeProv()
    voz.sintetizar, main_mod.VOZ_TIMEOUT_TOTAL = sintetizar_lento, 0.05
    os.environ.update({"OPENAI_API_KEY": "sk-test", "PUBLIC_URL": "https://agente.test", "HUMANIZAR": "false"})
    try:
        await main_mod.procesar_mensaje(MensajeEntrante(telefono=tel, texto="", mensaje_id="t3", audio_ref="m2"))
    finally:
        (brain.generar_respuesta, voz.transcribir, main_mod.proveedor, voz.sintetizar,
         main_mod.VOZ_TIMEOUT_TOTAL) = reales_voz
        for var in ("OPENAI_API_KEY", "PUBLIC_URL", "HUMANIZAR"):
            os.environ.pop(var, None)
    assert audios == [] and textos == ["Claro que sí, la hora está en $3.500"]


def test_voz_fluida_solo_en_turnos_de_voz():
    asyncio.run(_test_voz_fluida_solo_en_turnos_de_voz())


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
    test_precios_decimal()
    test_duracion_audio()
    test_modelo_default_haiku()
    test_costo_llm_registrado_y_fallo_no_rompe()
    test_tts_openai_payload_y_costo()
    test_estado_costo()
    test_precios_modelos_claude_y_json_malo()
    test_voz_valores_de_otro_proveedor()
    test_estado_costo_falla_no_rompe()
    test_es_fiel()
    test_tts_gpt_audio_payload_guarda_y_costo()
    test_voz_fluida_solo_en_turnos_de_voz()
    print("OK — todos los self-checks pasaron")
