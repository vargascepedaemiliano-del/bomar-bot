"""
BOMAR Bot - Backend (copia adaptada del bot de GECTAM, versión 2)

  - El bot conoce los servicios de BOMAR (bomar_info.py y la base de datos).
  - Recuerda la conversación (por session_id).
  - Guarda conversaciones y solicitudes en SQLite.
  - Este mismo servidor entrega el widget del chat (/widget.js) y el panel
    de administrador (/admin), así no hace falta otro hosting.
"""

import hmac
import os
import re
import time
from pathlib import Path
from typing import Literal, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import cotizador
import database

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "Falta ANTHROPIC_API_KEY. Crea un archivo .env en la carpeta backend "
        "(usa .env.example como base) con tu API key de Anthropic."
    )

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Crea las tablas y las áreas de servicio si la base de datos no existe
database.init_db()

app = FastAPI(title="BOMAR Bot API")

# CORS: solo bomar.mx puede usar el chat desde el navegador.
# Para probar en otro lado, en Render agrega la variable ALLOWED_ORIGINS
# con los dominios separados por comas.
ORIGENES = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "https://bomar.mx,https://www.bomar.mx").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC = Path(__file__).resolve().parent / "static"
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ChatMessage(BaseModel):
    message: str = Field(..., max_length=2000)
    session_id: str = Field(..., description="Identificador de la conversación (lo genera el widget)")


class ChatResponse(BaseModel):
    reply: str


@app.get("/")
def root():
    return {"status": "ok", "service": "BOMAR Bot API", "version": 1}


@app.get("/widget.js")
def widget():
    # El sitio de WordPress carga el chat desde aquí con una sola línea <script>.
    return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html", media_type="text/html")


@app.get("/styles.css")
def admin_styles():
    return FileResponse(STATIC / "styles.css", media_type="text/css")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatMessage):
    if not SESSION_RE.match(payload.session_id):
        raise HTTPException(status_code=400, detail="session_id inválido")

    if not payload.message.strip():
        return ChatResponse(reply="No recibí ningún mensaje, ¿puedes escribir de nuevo?")

    try:
        reply = cotizador.responder(client, payload.session_id, payload.message)
    except Exception as e:
        # No exponemos el detalle al cliente final; queda en los logs de Render.
        print(f"[ERROR] /chat falló: {e!r}")
        raise HTTPException(status_code=500, detail="El asistente no está disponible por el momento.")

    return ChatResponse(reply=reply)


@app.get("/chat/{session_id}/historial")
def historial(session_id: str):
    """
    Mensajes de una conversación, para que el widget pueda reabrirla.
    Solo los ve quien tiene el session_id (un código aleatorio que guarda
    el navegador del cliente).
    """
    if not SESSION_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id inválido")
    return [
        {"remitente": m["remitente"], "mensaje": m["mensaje"]}
        for m in database.mensajes_de_sesion(session_id)
    ]


# ---------------------------------------------------------------------------
# Panel de administrador
# Se protege con una contraseña que pones en Render como variable de entorno
# ADMIN_PASSWORD. Si no existe esa variable, el panel queda desactivado.
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def requiere_admin(x_admin_password: str = Header(default="")):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Panel de administrador desactivado: falta ADMIN_PASSWORD en el servidor.")
    if not hmac.compare_digest(x_admin_password.encode(), ADMIN_PASSWORD.encode()):
        time.sleep(1)  # frena intentos repetidos de adivinar la contraseña
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")


class ServicioIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    descripcion: Optional[str] = Field(default="", max_length=500)
    precio: Optional[float] = Field(default=None, ge=0)
    tipo_precio: Literal["fijo", "variable"] = "variable"
    cotizable_automatico: bool = False


@app.get("/admin/resumen", dependencies=[Depends(requiere_admin)])
def admin_resumen():
    return database.estadisticas()


@app.get("/admin/sesiones", dependencies=[Depends(requiere_admin)])
def admin_sesiones():
    return database.listar_sesiones()


@app.get("/admin/sesiones/{session_id}", dependencies=[Depends(requiere_admin)])
def admin_sesion(session_id: str):
    return database.mensajes_de_sesion(session_id)


@app.get("/admin/cotizaciones", dependencies=[Depends(requiere_admin)])
def admin_cotizaciones():
    return database.listar_cotizaciones()


@app.get("/admin/servicios", dependencies=[Depends(requiere_admin)])
def admin_servicios():
    return database.obtener_catalogo()


@app.post("/admin/servicios", dependencies=[Depends(requiere_admin)])
def admin_crear_servicio(s: ServicioIn):
    nuevo_id = database.crear_servicio(s.nombre, s.descripcion, None, "variable", False)
    return {"id": nuevo_id}


@app.put("/admin/servicios/{servicio_id}", dependencies=[Depends(requiere_admin)])
def admin_actualizar_servicio(servicio_id: int, s: ServicioIn):
    if not database.actualizar_servicio(servicio_id, s.nombre, s.descripcion, None, "variable", False):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    return {"ok": True}


@app.delete("/admin/servicios/{servicio_id}", dependencies=[Depends(requiere_admin)])
def admin_borrar_servicio(servicio_id: int):
    if not database.borrar_servicio(servicio_id):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    return {"ok": True}
