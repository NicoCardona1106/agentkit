# agentkit/memory.py — Persistencia: conversaciones, clientes, leads, tickets y pausas
# SQLite en local, PostgreSQL en producción (via DATABASE_URL).

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import DateTime, Float, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv(find_dotenv(usecwd=True))  # el .env vive en la carpeta del agente (cwd), no junto al paquete

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    __tablename__ = "mensajes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Cliente(Base):
    """Memoria de largo plazo por cliente: nombre, notas, intereses."""
    __tablename__ = "clientes"
    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), default="")
    notas: Mapped[str] = mapped_column(Text, default="")
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(100), default="")
    interes: Mapped[str] = mapped_column(Text, default="")
    presupuesto: Mapped[str] = mapped_column(String(100), default="")
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    problema: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="abierto")
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Pausa(Base):
    """Conversación pausada (derivada a humano): el bot no responde hasta `hasta`."""
    __tablename__ = "pausas"
    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)
    hasta: Mapped[datetime] = mapped_column(DateTime)


class Borrador(Base):
    """Respuesta pendiente de aprobación del equipo (MODO_BORRADOR)."""
    __tablename__ = "borradores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    texto: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | enviado | descartado
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UsoApi(Base):
    """Una fila por llamada a una API paga (LLM, STT, TTS), con su costo en USD (ver precios.py)."""
    __tablename__ = "uso_api"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)  # UTC
    tipo: Mapped[str] = mapped_column(String(10))  # llm | stt | tts
    proveedor: Mapped[str] = mapped_column(String(30))
    modelo: Mapped[str] = mapped_column(String(100))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_lectura: Mapped[int] = mapped_column(Integer, default=0)
    tokens_cache_escritura: Mapped[int] = mapped_column(Integer, default=0)
    segundos_audio: Mapped[float | None] = mapped_column(Float, nullable=True)
    caracteres: Mapped[int] = mapped_column(Integer, default=0)
    # Decimal en texto: SQLite no tiene decimal exacto; se suma con Decimal en Python
    usd: Mapped[str] = mapped_column(String(40))


async def inicializar_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Conversación ──────────────────────────────────────────────

async def guardar_mensaje(telefono: str, role: str, content: str):
    async with async_session() as session:
        session.add(Mensaje(telefono=telefono, role=role, content=content))
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """Últimos N mensajes en orden cronológico, como [{"role", "content"}]."""
    async with async_session() as session:
        q = (select(Mensaje).where(Mensaje.telefono == telefono)
             .order_by(Mensaje.timestamp.desc(), Mensaje.id.desc()).limit(limite))
        mensajes = list((await session.execute(q)).scalars().all())
        mensajes.reverse()
        return [{"role": m.role, "content": m.content} for m in mensajes]


async def limpiar_historial(telefono: str):
    async with async_session() as session:
        await session.execute(delete(Mensaje).where(Mensaje.telefono == telefono))
        await session.commit()


# ── Cliente (memoria de largo plazo) ──────────────────────────

async def obtener_cliente(telefono: str) -> dict:
    async with async_session() as session:
        c = await session.get(Cliente, telefono)
        return {"nombre": c.nombre, "notas": c.notas} if c else {"nombre": "", "notas": ""}


async def guardar_dato_cliente(telefono: str, nombre: str = "", nota: str = ""):
    async with async_session() as session:
        c = await session.get(Cliente, telefono)
        if not c:
            c = Cliente(telefono=telefono)
            session.add(c)
        if nombre:
            c.nombre = nombre
        if nota:
            c.notas = (c.notas + "\n" + nota).strip() if c.notas else nota
        c.actualizado = datetime.utcnow()
        await session.commit()


# ── Leads y tickets ───────────────────────────────────────────

async def crear_lead(telefono: str, nombre: str, interes: str, presupuesto: str = "") -> int:
    async with async_session() as session:
        lead = Lead(telefono=telefono, nombre=nombre, interes=interes, presupuesto=presupuesto)
        session.add(lead)
        await session.commit()
        return lead.id


async def crear_ticket(telefono: str, problema: str) -> int:
    async with async_session() as session:
        ticket = Ticket(telefono=telefono, problema=problema)
        session.add(ticket)
        await session.commit()
        return ticket.id


# ── Pausas (traspaso a humano) ────────────────────────────────

async def pausar_conversacion(telefono: str, minutos: int = 60):
    async with async_session() as session:
        p = await session.get(Pausa, telefono)
        hasta = datetime.utcnow() + timedelta(minutes=minutos)
        if p:
            p.hasta = hasta
        else:
            session.add(Pausa(telefono=telefono, hasta=hasta))
        await session.commit()


async def conversacion_pausada(telefono: str) -> bool:
    async with async_session() as session:
        p = await session.get(Pausa, telefono)
        return bool(p and p.hasta > datetime.utcnow())


# ── Borradores (MODO_BORRADOR) ────────────────────────────────

async def crear_borrador(telefono: str, texto: str) -> int:
    async with async_session() as session:
        b = Borrador(telefono=telefono, texto=texto)
        session.add(b)
        await session.commit()
        return b.id


async def resolver_borrador(bid: int, estado: str, texto: str = "") -> dict | None:
    """Marca un borrador pendiente como enviado/descartado.
    Devuelve {telefono, texto} o None si no existe o ya fue resuelto."""
    async with async_session() as session:
        b = await session.get(Borrador, bid)
        if not b or b.estado != "pendiente":
            return None
        b.estado = estado
        if texto:
            b.texto = texto
        await session.commit()
        return {"telefono": b.telefono, "texto": b.texto}


async def borradores_pendientes(limite: int = 10) -> list[dict]:
    async with async_session() as session:
        q = (select(Borrador).where(Borrador.estado == "pendiente")
             .order_by(Borrador.id.desc()).limit(limite))
        return [{"id": b.id, "telefono": b.telefono, "texto": b.texto}
                for b in (await session.execute(q)).scalars().all()]


# ── Reporte diario ────────────────────────────────────────────

async def resumen_dia() -> dict:
    """Conteos de hoy (UTC) para el reporte al equipo."""
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as session:
        leads = (await session.execute(select(Lead).where(Lead.creado >= hoy))).scalars().all()
        tickets = (await session.execute(select(Ticket).where(Ticket.creado >= hoy))).scalars().all()
        conversaciones = (await session.execute(
            select(func.count(func.distinct(Mensaje.telefono))).where(Mensaje.timestamp >= hoy)
        )).scalar() or 0
        return {
            "conversaciones": conversaciones,
            "leads": [{"nombre": l.nombre, "interes": l.interes, "telefono": l.telefono} for l in leads],
            "tickets": [{"id": t.id, "problema": t.problema, "telefono": t.telefono} for t in tickets],
        }


# ── Estado del agente (panel externo, GET /estado) ────────────

async def resumen_estado() -> dict:
    """Conteos de las últimas 24h (ventana móvil UTC, no "desde las 00:00") para GET /estado."""
    desde = datetime.utcnow() - timedelta(hours=24)
    async with async_session() as session:
        por_role = dict((await session.execute(
            select(Mensaje.role, func.count()).where(Mensaje.timestamp >= desde).group_by(Mensaje.role)
        )).all())
        entrantes = por_role.get("user", 0)
        salientes = por_role.get("assistant", 0)
        conversaciones = (await session.execute(select(func.count(func.distinct(Mensaje.telefono))).where(
            Mensaje.timestamp >= desde))).scalar() or 0
        leads = (await session.execute(select(func.count()).select_from(Lead).where(
            Lead.creado >= desde))).scalar() or 0
        tickets = (await session.execute(select(func.count()).select_from(Ticket).where(
            Ticket.creado >= desde))).scalar() or 0
        tickets_abiertos = (await session.execute(select(func.count()).select_from(Ticket).where(
            Ticket.estado == "abierto"))).scalar() or 0
        borradores = (await session.execute(select(func.count()).select_from(Borrador).where(
            Borrador.estado == "pendiente"))).scalar() or 0
        ultimo = (await session.execute(select(func.max(Mensaje.timestamp)))).scalar()
        return {
            "ultimas_24h": {
                "mensajes_entrantes": entrantes,
                "mensajes_salientes": salientes,
                "conversaciones": conversaciones,
                "leads": leads,
                "tickets": tickets,
            },
            "tickets_abiertos": tickets_abiertos,
            "ultimo_mensaje": ultimo.isoformat() + "Z" if ultimo else None,
            "borradores_pendientes": borradores,
        }


# ── Costo de las APIs (uso_api) ───────────────────────────────

# ponytail: offset fijo; Colombia no tiene horario de verano y zoneinfo pediría tzdata en Windows
BOGOTA = timezone(timedelta(hours=-5))


async def registrar_uso(**campos):
    async with async_session() as session:
        session.add(UsoApi(**campos))
        await session.commit()


async def resumen_costos() -> dict:
    """Costo en USD de hoy y del mes en curso (días de Bogotá), desglose del mes por tipo y los
    modelos usados este mes que no tienen precio (se registraron con costo 0).
    Los valores van como texto decimal (6 decimales) para que ningún float toque el dinero."""
    from agentkit import precios  # aquí y no arriba: precios importa memory
    hoy = datetime.now(BOGOTA).replace(hour=0, minute=0, second=0, microsecond=0)
    desde_hoy = hoy.astimezone(timezone.utc).replace(tzinfo=None)  # creado_en se guarda en UTC naive
    desde_mes = hoy.replace(day=1).astimezone(timezone.utc).replace(tzinfo=None)
    # ponytail: suma en Python con Decimal; un mes de un agente son miles de filas, no millones
    async with async_session() as session:
        filas = (await session.execute(select(UsoApi.tipo, UsoApi.usd, UsoApi.creado_en, UsoApi.modelo).where(
            UsoApi.creado_en >= desde_mes))).all()
    total_hoy = Decimal(0)
    desglose = {"llm": Decimal(0), "stt": Decimal(0), "tts": Decimal(0)}
    for tipo, usd, creado, _ in filas:
        desglose[tipo] = desglose.get(tipo, Decimal(0)) + Decimal(usd)
        if creado >= desde_hoy:
            total_hoy += Decimal(usd)

    def texto(d: Decimal) -> str:
        return format(d.quantize(Decimal("0.000001")), "f")

    return {
        "hoy": texto(total_hoy),
        "mes": texto(sum(desglose.values(), Decimal(0))),
        "desglose": {t: texto(v) for t, v in desglose.items()},
        "modelos_sin_precio": sorted({m for *_, m in filas if not precios.tiene_precio(m)}),
    }
