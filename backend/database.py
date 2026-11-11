"""
BOMAR Bot - Base de datos (copia adaptada del bot de GECTAM)

Este módulo crea y maneja la base de datos SQLite del proyecto.
Contiene 3 tablas:
  - servicios: las áreas de servicio de BOMAR
  - conversaciones: el historial de mensajes de cada sesión de chat
  - cotizaciones: las solicitudes de cotización/asesoría que deja cada cliente
    (BOMAR no maneja precios fijos, así que el total queda vacío)

No depende de la API de Claude para nada de lo que hace aquí.
"""

import os
import sqlite3
from datetime import datetime

# Ruta absoluta: siempre queda junto a este archivo (carpeta backend),
# sin importar desde dónde se ejecute el programa.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bomar.db")


def get_connection():
    """Abre una conexión a la base de datos SQLite."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # permite acceder a columnas por nombre
    return conn


def init_db():
    """Crea las tablas si no existen todavía, y siembra datos de ejemplo."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            precio REAL,
            tipo_precio TEXT DEFAULT 'fijo',       -- 'fijo' o 'variable'
            cotizable_automatico INTEGER DEFAULT 1  -- 1 = sí, 0 = no (requiere que un humano cotice)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            remitente TEXT NOT NULL,   -- 'cliente' o 'bot'
            mensaje TEXT NOT NULL,
            fecha TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cotizaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            cliente_nombre TEXT,
            cliente_contacto TEXT,
            resumen TEXT,
            total REAL,
            fecha TEXT NOT NULL
        )
    """)

    conn.commit()

    # --- Áreas de servicio de BOMAR (tomadas de bomar.mx) ---
    # Ninguna tiene precio fijo: todas las cotiza una persona de BOMAR.
    cur.execute("SELECT COUNT(*) FROM servicios")
    if cur.fetchone()[0] == 0:
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
        cur.executemany(
            "INSERT INTO servicios (nombre, descripcion, precio, tipo_precio, cotizable_automatico) VALUES (?, ?, NULL, 'variable', 0)",
            servicios,
        )
        conn.commit()

    conn.close()


def guardar_mensaje(session_id: str, remitente: str, mensaje: str):
    """Guarda un mensaje (del cliente o del bot) en el historial."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO conversaciones (session_id, remitente, mensaje, fecha) VALUES (?, ?, ?, ?)",
        (session_id, remitente, mensaje, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def obtener_historial(session_id: str, limite: int = 20):
    """
    Devuelve los últimos mensajes de una sesión, en orden cronológico,
    listos para mandarle a Claude como historial de la conversación.
    """
    conn = get_connection()
    filas = conn.execute(
        "SELECT remitente, mensaje FROM conversaciones WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limite),
    ).fetchall()
    conn.close()
    return list(reversed(filas))  # los regresamos en orden cronológico


def obtener_catalogo():
    """Devuelve todos los servicios del catálogo."""
    conn = get_connection()
    filas = conn.execute("SELECT * FROM servicios").fetchall()
    conn.close()
    return [dict(f) for f in filas]


def guardar_cotizacion(session_id: str, cliente_nombre: str, cliente_contacto: str, resumen: str, total: float):
    """Guarda una cotización generada, para que el panel administrativo la vea."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO cotizaciones (session_id, cliente_nombre, cliente_contacto, resumen, total, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, cliente_nombre, cliente_contacto, resumen, total, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Funciones para el panel de administrador
# ---------------------------------------------------------------------------

def estadisticas():
    """Números generales para la pantalla de resumen del administrador."""
    conn = get_connection()
    sesiones = conn.execute("SELECT COUNT(DISTINCT session_id) FROM conversaciones").fetchone()[0]
    mensajes = conn.execute("SELECT COUNT(*) FROM conversaciones WHERE remitente = 'cliente'").fetchone()[0]
    cot = conn.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM cotizaciones").fetchone()
    conn.close()
    return {
        "sesiones": sesiones,
        "mensajes_cliente": mensajes,
        "cotizaciones": cot[0],
        "total_cotizado": cot[1],
    }


def listar_sesiones(limite: int = 200):
    """Una fila por conversación: cuándo empezó, cuántos mensajes y si generó cotización."""
    conn = get_connection()
    filas = conn.execute(
        """
        SELECT c.session_id,
               MIN(c.fecha) AS inicio,
               MAX(c.fecha) AS ultimo,
               COUNT(*) AS mensajes,
               (SELECT mensaje FROM conversaciones x
                 WHERE x.session_id = c.session_id AND x.remitente = 'cliente'
                 ORDER BY x.id ASC LIMIT 1) AS primer_mensaje,
               (SELECT COUNT(*) FROM cotizaciones q WHERE q.session_id = c.session_id) AS cotizaciones
        FROM conversaciones c
        GROUP BY c.session_id
        ORDER BY ultimo DESC
        LIMIT ?
        """,
        (limite,),
    ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def mensajes_de_sesion(session_id: str):
    """Todos los mensajes de una conversación, en orden."""
    conn = get_connection()
    filas = conn.execute(
        "SELECT remitente, mensaje, fecha FROM conversaciones WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def listar_cotizaciones(limite: int = 200):
    """Las cotizaciones generadas, de la más reciente a la más antigua."""
    conn = get_connection()
    filas = conn.execute("SELECT * FROM cotizaciones ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def crear_servicio(nombre, descripcion, precio, tipo_precio, cotizable_automatico):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO servicios (nombre, descripcion, precio, tipo_precio, cotizable_automatico) VALUES (?, ?, ?, ?, ?)",
        (nombre, descripcion, precio, tipo_precio, 1 if cotizable_automatico else 0),
    )
    conn.commit()
    nuevo_id = cur.lastrowid
    conn.close()
    return nuevo_id


def actualizar_servicio(servicio_id, nombre, descripcion, precio, tipo_precio, cotizable_automatico):
    """Devuelve True si el servicio existía."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE servicios SET nombre=?, descripcion=?, precio=?, tipo_precio=?, cotizable_automatico=? WHERE id=?",
        (nombre, descripcion, precio, tipo_precio, 1 if cotizable_automatico else 0, servicio_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def borrar_servicio(servicio_id):
    """Devuelve True si el servicio existía."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM servicios WHERE id = ?", (servicio_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


if __name__ == "__main__":
    # Puedes correr este archivo solo (python database.py) para crear
    # la base de datos sin tener que levantar el servidor completo.
    init_db()
    print(f"Base de datos '{DB_NAME}' creada/actualizada correctamente.")
    print("Catálogo actual:")
    for s in obtener_catalogo():
        print(" -", s)
