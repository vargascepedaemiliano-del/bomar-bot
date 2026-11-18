"""
BOMAR Bot - Backend (FastAPI)

  /chat                    el chat del sitio (con límite anti-abuso)
  /chat/{id}/historial     para reabrir una conversación desde el widget
  /widget.js               la burbuja de chat que se pega en WordPress
  /admin                   panel del dueño (clientes, cotizaciones, precios)
  /admin/...               API del panel, protegida con ADMIN_PASSWORD
"""

import csv
import hmac
import io
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import cotizador
import database
import notificaciones
from bomar_info import CORREO, TELEFONO

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "Falta ANTHROPIC_API_KEY. Crea un archivo .env en la carpeta backend "
        "(usa .env.example como base) con tu API key de Anthropic."
    )

client = Anthropic(api_key=ANTHROPIC_API_KEY)
database.init_db()

app = FastAPI(title="BOMAR Bot API", docs_url=None, redoc_url=None)

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


# ---------------------------------------------------------------------------
# Límite anti-abuso (para que nadie gaste el saldo de la API mandando spam)
# ---------------------------------------------------------------------------

LIMITE_IP = int(os.getenv("LIMITE_MENSAJES_IP", "25"))        # mensajes por IP...
VENTANA_IP = int(os.getenv("VENTANA_SEGUNDOS_IP", "600"))     # ...cada 10 minutos
LIMITE_SESION = int(os.getenv("LIMITE_MENSAJES_SESION", "80"))  # mensajes por conversación
_por_ip: dict[str, deque] = defaultdict(deque)


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _excede_limite(ip: str) -> bool:
    ahora = time.time()
    q = _por_ip[ip]
    while q and q[0] < ahora - VENTANA_IP:
        q.popleft()
    if len(q) >= LIMITE_IP:
        return True
    q.append(ahora)
    if len(_por_ip) > 5000:  # limpieza simple de memoria
        for k in [k for k, v in _por_ip.items() if not v]:
            del _por_ip[k]
    return False


# ---------------------------------------------------------------------------
# Rutas públicas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    message: str = Field(..., max_length=2000)
    session_id: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/")
def root():
    return {"status": "ok", "service": "BOMAR Bot API", "version": 2}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/widget.js")
def widget():
    return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html", media_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatMessage, request: Request):
    if not SESSION_RE.match(payload.session_id):
        raise HTTPException(status_code=400, detail="session_id inválido")
    if not payload.message.strip():
        return ChatResponse(reply="No recibí ningún mensaje, ¿puede escribir de nuevo?")

    if _excede_limite(_ip(request)):
        return ChatResponse(reply=(
            "Ha enviado muchos mensajes en poco tiempo. Espere unos minutos, o contáctenos directamente "
            f"al {TELEFONO} o a {CORREO}."
        ))
    if database.mensajes_cliente_en_sesion(payload.session_id) >= LIMITE_SESION:
        return ChatResponse(reply=(
            "Esta conversación llegó a su límite de mensajes. Puede abrir una conversación nueva, "
            f"o contactarnos al {TELEFONO} o a {CORREO}."
        ))

    try:
        reply = cotizador.responder(client, payload.session_id, payload.message)
    except Exception as e:
        print(f"[ERROR] /chat falló: {e!r}")
        raise HTTPException(status_code=500, detail="El asistente no está disponible por el momento.")
    return ChatResponse(reply=reply)


@app.get("/chat/{session_id}/historial")
def historial(session_id: str):
    if not SESSION_RE.match(session_id):
        raise HTTPException(status_code=400, detail="session_id inválido")
    return [{"remitente": m["remitente"], "mensaje": m["mensaje"]} for m in database.mensajes_de_sesion(session_id)]


# ---------------------------------------------------------------------------
# Panel de administrador (contraseña en la variable ADMIN_PASSWORD)
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
_fallos_admin: dict[str, deque] = defaultdict(deque)


def requiere_admin(request: Request, x_admin_password: str = Header(default="")):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Panel desactivado: falta ADMIN_PASSWORD en el servidor.")
    ip = _ip(request)
    fallos = _fallos_admin[ip]
    while fallos and fallos[0] < time.time() - 900:
        fallos.popleft()
    if len(fallos) >= 10:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espere 15 minutos.")
    if not hmac.compare_digest(x_admin_password.encode(), ADMIN_PASSWORD.encode()):
        fallos.append(time.time())
        time.sleep(1)
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")


admin = [Depends(requiere_admin)]


@app.get("/admin/resumen", dependencies=admin)
def admin_resumen():
    datos = database.estadisticas()
    datos["correo_configurado"] = notificaciones.correo_configurado()
    datos["disco_permanente"] = bool(os.getenv("DB_PATH"))
    return datos


# --- Cotizaciones ---

class SolicitudPatch(BaseModel):
    estado: Optional[Literal["nueva", "contactado", "cotizado", "cerrada", "descartada"]] = None
    notas: Optional[str] = Field(default=None, max_length=4000)


@app.get("/admin/solicitudes", dependencies=admin)
def admin_solicitudes(estado: str = "", buscar: str = ""):
    if estado and estado not in database.ESTADOS:
        raise HTTPException(status_code=400, detail="Estado inválido.")
    return database.listar_solicitudes(estado=estado, buscar=buscar.strip()[:80])


@app.patch("/admin/solicitudes/{solicitud_id}", dependencies=admin)
def admin_actualizar_solicitud(solicitud_id: int, cambios: SolicitudPatch):
    if not database.actualizar_solicitud(solicitud_id, cambios.estado, cambios.notas):
        raise HTTPException(status_code=404, detail="Cotización no encontrada.")
    return database.obtener_solicitud(solicitud_id)


@app.delete("/admin/solicitudes/{solicitud_id}", dependencies=admin)
def admin_borrar_solicitud(solicitud_id: int):
    if not database.borrar_solicitud(solicitud_id):
        raise HTTPException(status_code=404, detail="Cotización no encontrada.")
    return {"ok": True}


@app.get("/admin/export.csv", dependencies=admin)
def admin_exportar():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Folio", "Fecha", "Estado", "Cliente", "Teléfono", "Correo", "Empresa",
                "Servicio", "Ubicación", "Descripción", "Presupuesto", "Total MXN", "Notas"])
    for s in database.listar_solicitudes(limite=100000):
        w.writerow([s["folio"], s["creado"], s["estado"], s["cliente_nombre"], s["cliente_telefono"],
                    s["cliente_correo"], s["cliente_empresa"], s["servicio"], s["ubicacion"], s["descripcion"],
                    s["detalle"], "" if s["total"] is None else f"{s['total']:.2f}", s["notas"]])
    contenido = "﻿" + buf.getvalue()  # BOM para que Excel respete los acentos
    return Response(content=contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="cotizaciones-bomar.csv"'})


# --- Clientes ---

class NotasIn(BaseModel):
    notas: str = Field(default="", max_length=4000)


@app.get("/admin/clientes", dependencies=admin)
def admin_clientes(buscar: str = ""):
    return database.listar_clientes(buscar.strip()[:80])


@app.get("/admin/clientes/{cliente_id}", dependencies=admin)
def admin_cliente(cliente_id: int):
    c = database.obtener_cliente(cliente_id)
    if not c:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return c


@app.patch("/admin/clientes/{cliente_id}", dependencies=admin)
def admin_notas_cliente(cliente_id: int, datos: NotasIn):
    if not database.actualizar_notas_cliente(cliente_id, datos.notas):
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    return {"ok": True}


# --- Conversaciones ---

@app.get("/admin/sesiones", dependencies=admin)
def admin_sesiones():
    return database.listar_sesiones()


@app.get("/admin/sesiones/{session_id}", dependencies=admin)
def admin_sesion(session_id: str):
    return database.mensajes_de_sesion(session_id)


# --- Servicios y precios ---

class ServicioIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    descripcion: str = Field(default="", max_length=500)
    precio: Optional[float] = Field(default=None, ge=0)
    unidad: str = Field(default="servicio", min_length=1, max_length=40)
    tipo_precio: Literal["manual", "fijo", "desde"] = "manual"
    activo: bool = True


def _validar_servicio(s: ServicioIn):
    if s.tipo_precio != "manual" and s.precio is None:
        raise HTTPException(status_code=400, detail="Pon un precio, o elige 'Sin precio (lo cotiza un ingeniero)'.")
    return None if s.tipo_precio == "manual" else s.precio


@app.get("/admin/servicios", dependencies=admin)
def admin_servicios():
    return database.obtener_catalogo()


@app.post("/admin/servicios", dependencies=admin)
def admin_crear_servicio(s: ServicioIn):
    precio = _validar_servicio(s)
    return {"id": database.crear_servicio(s.nombre, s.descripcion, precio, s.unidad, s.tipo_precio, s.activo)}


@app.put("/admin/servicios/{servicio_id}", dependencies=admin)
def admin_actualizar_servicio(servicio_id: int, s: ServicioIn):
    precio = _validar_servicio(s)
    if not database.actualizar_servicio(servicio_id, s.nombre, s.descripcion, precio, s.unidad, s.tipo_precio, s.activo):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    return {"ok": True}


@app.delete("/admin/servicios/{servicio_id}", dependencies=admin)
def admin_borrar_servicio(servicio_id: int):
    if not database.borrar_servicio(servicio_id):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    return {"ok": True}


# --- Correo ---

@app.post("/admin/probar-correo", dependencies=admin)
def admin_probar_correo():
    ok, mensaje = notificaciones.enviar_prueba()
    if not ok:
        raise HTTPException(status_code=400, detail=mensaje)
    return {"ok": True, "mensaje": mensaje}
