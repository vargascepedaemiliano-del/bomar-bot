"""
BOMAR Bot - Base de datos (SQLite)

Tablas:
  - servicios:      catálogo de BOMAR con su precio (o sin precio = cotización manual)
  - clientes:       cada cliente, identificado por su teléfono
  - sesiones:       une cada chat (session_id) con su cliente y guarda el "corte"
                    que se hace al escribir NUEVA COTIZACIÓN
  - conversaciones: todos los mensajes de cada chat
  - solicitudes:    cada cotización, con folio (BOM-0001), estado y notas del dueño

La ruta del archivo se configura con la variable DB_PATH. En Render apunta
al disco permanente (por ejemplo /var/data/bomar.db) para que nada se borre.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

DB_NAME = os.getenv("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bomar.db")
ZONA = ZoneInfo("America/Monterrey")

ESTADOS = ("nueva", "contactado", "cotizado", "cerrada", "descartada")
TIPOS_PRECIO = ("manual", "fijo", "desde")


def ahora() -> str:
    return datetime.now(ZONA).isoformat(timespec="seconds")


def normalizar_telefono(tel: str) -> str:
    """Deja solo dígitos y quita la lada de país 52 / 521 de México."""
    d = re.sub(r"\D", "", tel or "")
    if len(d) == 13 and d.startswith("521"):
        d = d[3:]
    elif len(d) == 12 and d.startswith("52"):
        d = d[2:]
    return d


@contextmanager
def conexion():
    conn = sqlite3.connect(DB_NAME, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _filas(cur):
    return [dict(f) for f in cur.fetchall()]


# ---------------------------------------------------------------------------
# Creación de tablas
# ---------------------------------------------------------------------------

def init_db():
    carpeta = os.path.dirname(DB_NAME)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    with conexion() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS servicios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                descripcion TEXT DEFAULT '',
                precio REAL,                         -- NULL = sin precio
                unidad TEXT DEFAULT 'servicio',      -- ej. 'servicio', 'equipo', 'km', 'm2'
                tipo_precio TEXT DEFAULT 'manual',   -- manual | fijo | desde
                activo INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL UNIQUE,       -- solo dígitos, 10 en México
                correo TEXT DEFAULT '',
                empresa TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                creado TEXT NOT NULL,
                actualizado TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sesiones (
                session_id TEXT PRIMARY KEY,
                cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
                corte_id INTEGER DEFAULT 0,          -- id del último mensaje antes de NUEVA COTIZACIÓN
                creado TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                remitente TEXT NOT NULL,             -- 'cliente' o 'bot'
                mensaje TEXT NOT NULL,
                fecha TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conv_sesion ON conversaciones(session_id, id);

            CREATE TABLE IF NOT EXISTS solicitudes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folio TEXT UNIQUE,
                cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                session_id TEXT,
                servicio TEXT DEFAULT '',            -- resumen corto de lo que pide
                descripcion TEXT DEFAULT '',         -- detalle del proyecto
                ubicacion TEXT DEFAULT '',
                detalle TEXT DEFAULT '',             -- líneas del presupuesto
                total REAL,                          -- NULL si no hay precio
                total_es_estimado INTEGER DEFAULT 0, -- 1 si incluye precios "desde"
                requiere_revision INTEGER DEFAULT 0, -- 1 si hay conceptos sin precio
                estado TEXT DEFAULT 'nueva',
                notas TEXT DEFAULT '',
                creado TEXT NOT NULL,
                actualizado TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sol_cliente ON solicitudes(cliente_id);
        """)

        if c.execute("SELECT COUNT(*) FROM servicios").fetchone()[0] == 0:
            servicios = [
                ("Servicio Área Eléctrica", "Mantenimiento y puesta en servicio de subestaciones y líneas eléctricas"),
                ("Servicio Área Electromecánica", "Instalaciones industriales, motores, generadores, bombeo y enfriamiento"),
                ("Estudios", "Termografía, calidad de la energía, Código de Red, protecciones, corto circuito, Arc Flash y generadores"),
                ("Servicio Área Civil", "Construcción de edificios, subestaciones, líneas, terracerías, topografía y cálculo estructural"),
                ("Servicio de Ingenierías", "Ingeniería conceptual, básica y de detalle para el sector energético, industrial y residencial"),
                ("Servicio de Consultorías", "Cumplimiento del Código de Red en puntos de conexión e interconexión"),
                ("Servicio de Mantenimiento y Puesta en Servicio", "Subestaciones eléctricas en media y alta tensión"),
                ("Servicio de Gestoría", "Revisión de ingenierías para medición fiscal y nuevas subestaciones (115, 230 y 400 kV)"),
                ("Comercialización de equipos para el sector industrial", "Suministro e instalación de equipos electromecánicos de potencia y media tensión"),
            ]
            c.executemany(
                "INSERT INTO servicios (nombre, descripcion, precio, unidad, tipo_precio) VALUES (?, ?, NULL, 'servicio', 'manual')",
                servicios,
            )


# ---------------------------------------------------------------------------
# Catálogo de servicios
# ---------------------------------------------------------------------------

def obtener_catalogo(solo_activos=False):
    with conexion() as c:
        q = "SELECT * FROM servicios" + (" WHERE activo = 1" if solo_activos else "") + " ORDER BY id"
        return _filas(c.execute(q))


def crear_servicio(nombre, descripcion, precio, unidad, tipo_precio, activo=True):
    with conexion() as c:
        cur = c.execute(
            "INSERT INTO servicios (nombre, descripcion, precio, unidad, tipo_precio, activo) VALUES (?, ?, ?, ?, ?, ?)",
            (nombre, descripcion, precio, unidad, tipo_precio, 1 if activo else 0),
        )
        return cur.lastrowid


def actualizar_servicio(servicio_id, nombre, descripcion, precio, unidad, tipo_precio, activo=True):
    with conexion() as c:
        cur = c.execute(
            "UPDATE servicios SET nombre=?, descripcion=?, precio=?, unidad=?, tipo_precio=?, activo=? WHERE id=?",
            (nombre, descripcion, precio, unidad, tipo_precio, 1 if activo else 0, servicio_id),
        )
        return cur.rowcount > 0


def borrar_servicio(servicio_id):
    with conexion() as c:
        return c.execute("DELETE FROM servicios WHERE id = ?", (servicio_id,)).rowcount > 0


# ---------------------------------------------------------------------------
# Sesiones y mensajes
# ---------------------------------------------------------------------------

def asegurar_sesion(session_id):
    with conexion() as c:
        c.execute("INSERT OR IGNORE INTO sesiones (session_id, creado) VALUES (?, ?)", (session_id, ahora()))


def obtener_sesion(session_id):
    with conexion() as c:
        f = c.execute("SELECT * FROM sesiones WHERE session_id = ?", (session_id,)).fetchone()
        return dict(f) if f else None


def guardar_mensaje(session_id, remitente, mensaje):
    with conexion() as c:
        cur = c.execute(
            "INSERT INTO conversaciones (session_id, remitente, mensaje, fecha) VALUES (?, ?, ?, ?)",
            (session_id, remitente, mensaje, ahora()),
        )
        return cur.lastrowid


def marcar_corte(session_id):
    """NUEVA COTIZACIÓN: el bot deja de ver los mensajes anteriores de este chat."""
    with conexion() as c:
        ultimo = c.execute("SELECT COALESCE(MAX(id), 0) FROM conversaciones WHERE session_id = ?", (session_id,)).fetchone()[0]
        c.execute("UPDATE sesiones SET corte_id = ? WHERE session_id = ?", (ultimo, session_id))


def historial_para_ia(session_id, limite=30):
    """Mensajes posteriores al último corte, en orden, para mandarle a Claude."""
    with conexion() as c:
        corte = c.execute("SELECT corte_id FROM sesiones WHERE session_id = ?", (session_id,)).fetchone()
        corte = corte[0] if corte else 0
        filas = c.execute(
            "SELECT remitente, mensaje FROM conversaciones WHERE session_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
            (session_id, corte, limite),
        ).fetchall()
        return list(reversed(filas))


def mensajes_de_sesion(session_id):
    with conexion() as c:
        return _filas(c.execute(
            "SELECT remitente, mensaje, fecha FROM conversaciones WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ))


def mensajes_cliente_en_sesion(session_id):
    with conexion() as c:
        return c.execute(
            "SELECT COUNT(*) FROM conversaciones WHERE session_id = ? AND remitente = 'cliente'", (session_id,)
        ).fetchone()[0]


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

def registrar_cliente(session_id, nombre, telefono, correo="", empresa=""):
    """
    Crea o actualiza el cliente (se identifica por teléfono) y lo liga al chat.
    Devuelve (cliente_dict, es_nuevo).
    """
    tel = normalizar_telefono(telefono)
    with conexion() as c:
        existente = c.execute("SELECT * FROM clientes WHERE telefono = ?", (tel,)).fetchone()
        if existente:
            cid = existente["id"]
            c.execute(
                """UPDATE clientes SET nombre = ?, correo = COALESCE(NULLIF(?, ''), correo),
                   empresa = COALESCE(NULLIF(?, ''), empresa), actualizado = ? WHERE id = ?""",
                (nombre, correo, empresa, ahora(), cid),
            )
            es_nuevo = False
        else:
            cid = c.execute(
                "INSERT INTO clientes (nombre, telefono, correo, empresa, creado, actualizado) VALUES (?, ?, ?, ?, ?, ?)",
                (nombre, tel, correo, empresa, ahora(), ahora()),
            ).lastrowid
            es_nuevo = True
        c.execute("INSERT OR IGNORE INTO sesiones (session_id, creado) VALUES (?, ?)", (session_id, ahora()))
        c.execute("UPDATE sesiones SET cliente_id = ? WHERE session_id = ?", (cid, session_id))
        cliente = dict(c.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone())
    return cliente, es_nuevo


def cliente_de_sesion(session_id):
    with conexion() as c:
        f = c.execute(
            "SELECT cl.* FROM sesiones s JOIN clientes cl ON cl.id = s.cliente_id WHERE s.session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(f) if f else None


def listar_clientes(buscar=""):
    with conexion() as c:
        q = """
            SELECT cl.*,
                   COUNT(s.id) AS solicitudes,
                   MAX(s.creado) AS ultima_solicitud,
                   SUM(CASE WHEN s.estado = 'nueva' THEN 1 ELSE 0 END) AS pendientes
            FROM clientes cl LEFT JOIN solicitudes s ON s.cliente_id = cl.id
        """
        params = []
        if buscar:
            q += " WHERE cl.nombre LIKE ? OR cl.telefono LIKE ? OR cl.empresa LIKE ? OR cl.correo LIKE ?"
            like = f"%{buscar}%"
            params = [like, f"%{normalizar_telefono(buscar) or buscar}%", like, like]
        q += " GROUP BY cl.id ORDER BY COALESCE(MAX(s.creado), cl.actualizado) DESC LIMIT 500"
        return _filas(c.execute(q, params))


def obtener_cliente(cliente_id):
    with conexion() as c:
        f = c.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        if not f:
            return None
        cliente = dict(f)
        cliente["solicitudes"] = _filas(c.execute(
            "SELECT * FROM solicitudes WHERE cliente_id = ? ORDER BY id DESC", (cliente_id,)
        ))
        cliente["sesiones"] = [r[0] for r in c.execute(
            "SELECT session_id FROM sesiones WHERE cliente_id = ? ORDER BY creado DESC", (cliente_id,)
        )]
        return cliente


def actualizar_notas_cliente(cliente_id, notas):
    with conexion() as c:
        return c.execute(
            "UPDATE clientes SET notas = ?, actualizado = ? WHERE id = ?", (notas, ahora(), cliente_id)
        ).rowcount > 0


def folios_de_cliente(cliente_id, limite=5):
    with conexion() as c:
        return _filas(c.execute(
            "SELECT folio, servicio, estado, creado FROM solicitudes WHERE cliente_id = ? ORDER BY id DESC LIMIT ?",
            (cliente_id, limite),
        ))


# ---------------------------------------------------------------------------
# Solicitudes (cotizaciones)
# ---------------------------------------------------------------------------

def crear_solicitud(cliente_id, session_id, servicio, descripcion, ubicacion, detalle, total,
                    total_es_estimado, requiere_revision):
    with conexion() as c:
        sid = c.execute(
            """INSERT INTO solicitudes (cliente_id, session_id, servicio, descripcion, ubicacion, detalle, total,
                   total_es_estimado, requiere_revision, estado, creado, actualizado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'nueva', ?, ?)""",
            (cliente_id, session_id, servicio, descripcion, ubicacion, detalle, total,
             1 if total_es_estimado else 0, 1 if requiere_revision else 0, ahora(), ahora()),
        ).lastrowid
        folio = f"BOM-{sid:04d}"
        c.execute("UPDATE solicitudes SET folio = ? WHERE id = ?", (folio, sid))
    return obtener_solicitud(sid)


def obtener_solicitud(solicitud_id):
    with conexion() as c:
        f = c.execute(
            """SELECT s.*, cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono,
                      cl.correo AS cliente_correo, cl.empresa AS cliente_empresa
               FROM solicitudes s JOIN clientes cl ON cl.id = s.cliente_id WHERE s.id = ?""",
            (solicitud_id,),
        ).fetchone()
        return dict(f) if f else None


def listar_solicitudes(estado="", buscar="", limite=500):
    with conexion() as c:
        q = """SELECT s.*, cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono,
                      cl.correo AS cliente_correo, cl.empresa AS cliente_empresa
               FROM solicitudes s JOIN clientes cl ON cl.id = s.cliente_id WHERE 1=1"""
        params = []
        if estado:
            q += " AND s.estado = ?"
            params.append(estado)
        if buscar:
            like = f"%{buscar}%"
            q += """ AND (s.folio LIKE ? OR cl.nombre LIKE ? OR cl.telefono LIKE ? OR cl.empresa LIKE ?
                         OR s.servicio LIKE ? OR s.descripcion LIKE ?)"""
            params += [like, like, f"%{normalizar_telefono(buscar) or buscar}%", like, like, like]
        q += " ORDER BY s.id DESC LIMIT ?"
        params.append(limite)
        return _filas(c.execute(q, params))


def actualizar_solicitud(solicitud_id, estado=None, notas=None):
    campos, params = [], []
    if estado is not None:
        campos.append("estado = ?")
        params.append(estado)
    if notas is not None:
        campos.append("notas = ?")
        params.append(notas)
    if not campos:
        return True
    campos.append("actualizado = ?")
    params += [ahora(), solicitud_id]
    with conexion() as c:
        return c.execute(f"UPDATE solicitudes SET {', '.join(campos)} WHERE id = ?", params).rowcount > 0


def borrar_solicitud(solicitud_id):
    with conexion() as c:
        return c.execute("DELETE FROM solicitudes WHERE id = ?", (solicitud_id,)).rowcount > 0


# ---------------------------------------------------------------------------
# Panel: resumen y conversaciones
# ---------------------------------------------------------------------------

def estadisticas():
    hoy = datetime.now(ZONA).date().isoformat()
    mes = hoy[:7]
    with conexion() as c:
        uno = lambda q, p=(): c.execute(q, p).fetchone()[0]
        return {
            "nuevas": uno("SELECT COUNT(*) FROM solicitudes WHERE estado = 'nueva'"),
            "solicitudes_hoy": uno("SELECT COUNT(*) FROM solicitudes WHERE substr(creado, 1, 10) = ?", (hoy,)),
            "solicitudes_mes": uno("SELECT COUNT(*) FROM solicitudes WHERE substr(creado, 1, 7) = ?", (mes,)),
            "clientes": uno("SELECT COUNT(*) FROM clientes"),
            "conversaciones_mes": uno(
                "SELECT COUNT(DISTINCT session_id) FROM conversaciones WHERE substr(fecha, 1, 7) = ?", (mes,)),
            "presupuestado_mes": uno(
                "SELECT COALESCE(SUM(total), 0) FROM solicitudes WHERE substr(creado, 1, 7) = ?", (mes,)),
        }


def listar_sesiones(limite=300):
    with conexion() as c:
        return _filas(c.execute(
            """
            SELECT c.session_id,
                   MIN(c.fecha) AS inicio,
                   MAX(c.fecha) AS ultimo,
                   COUNT(*) AS mensajes,
                   (SELECT mensaje FROM conversaciones x WHERE x.session_id = c.session_id AND x.remitente = 'cliente'
                     ORDER BY x.id ASC LIMIT 1) AS primer_mensaje,
                   cl.id AS cliente_id, cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono,
                   (SELECT COUNT(*) FROM solicitudes q WHERE q.session_id = c.session_id) AS solicitudes
            FROM conversaciones c
            LEFT JOIN sesiones s ON s.session_id = c.session_id
            LEFT JOIN clientes cl ON cl.id = s.cliente_id
            GROUP BY c.session_id
            ORDER BY ultimo DESC
            LIMIT ?
            """,
            (limite,),
        ))


if __name__ == "__main__":
    init_db()
    print(f"Base de datos lista en: {DB_NAME}")
    for s in obtener_catalogo():
        print(" -", s["id"], s["nombre"], s["tipo_precio"], s["precio"])
