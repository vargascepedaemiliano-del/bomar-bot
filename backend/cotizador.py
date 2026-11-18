"""
BOMAR Bot - Lógica del asistente (sin FastAPI)

Flujo de una cotización:
  1. El bot entiende qué necesita el cliente y le explica los servicios.
  2. Le pide nombre y teléfono -> herramienta `registrar_cliente`
     (el cliente queda guardado por su teléfono; si ya existía, se reconoce).
  3. Confirma los conceptos -> herramienta `registrar_cotizacion`
     (este código calcula el presupuesto con los precios de la base de datos,
     genera el folio BOM-0001 y le avisa por correo al dueño).
  4. Si el cliente escribe NUEVA COTIZACIÓN (o usa el botón), el bot empieza
     una cotización desde cero en el mismo chat, sin volver a pedirle sus datos.

Regla importante: los precios y totales los calcula este código, nunca la IA.
"""

import json
import os
import re
import unicodedata

import database as db
import notificaciones
from bomar_info import CORREO, INFO_EMPRESA, TELEFONO

MODELO = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = 900
MAX_MENSAJE = 1000      # caracteres máximos por mensaje del cliente
MAX_VUELTAS_TOOL = 5    # evita ciclos infinitos con herramientas

PALABRA_CLAVE = "NUEVA COTIZACIÓN"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sin_acentos(t: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")


def es_palabra_clave(texto: str) -> bool:
    t = re.sub(r"[^a-z ]", " ", _sin_acentos(texto.lower()))
    t = re.sub(r"\s+", " ", t).strip()
    return t in ("nueva cotizacion", "otra cotizacion", "quiero una nueva cotizacion", "nueva")


def _dinero(v):
    return f"${v:,.2f} MXN"


def _precio_texto(s: dict) -> str:
    if s["tipo_precio"] == "manual" or s["precio"] is None:
        return "sin precio publicado: lo cotiza un ingeniero"
    unidad = s.get("unidad") or "servicio"
    if s["tipo_precio"] == "desde":
        return f"desde {_dinero(s['precio'])} por {unidad} (precio base, el final depende del proyecto)"
    return f"{_dinero(s['precio'])} por {unidad}"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def prompt_fijo(catalogo: list[dict]) -> str:
    """Parte del prompt que casi no cambia (se guarda en caché para ahorrar)."""
    lineas = "\n".join(
        f"- ID {s['id']}: {s['nombre']} — {s['descripcion'] or ''} | Precio: {_precio_texto(s)}"
        for s in catalogo
    ) or "(sin servicios registrados)"

    return f"""Eres el asistente virtual de BOMAR, empresa mexicana de construcción, ingeniería y consultoría para proyectos energéticos, industriales y residenciales. Atiendes a los visitantes de bomar.mx por chat, en español, con tono profesional, cordial y breve (máximo 5-6 líneas por respuesta, salvo que el cliente pida detalle). Hablas de "usted" salvo que el cliente tutee.

TU OBJETIVO
Que cada cliente salga con su solicitud de cotización registrada y bien explicada, para que el dueño de BOMAR solo tenga que revisar el panel y contactarlo.

CÓMO ATENDER
1. Entiende qué necesita el cliente. Explícale qué servicio de BOMAR le sirve, usando solo la información de abajo.
2. Reúne lo necesario para cotizar, con preguntas cortas (una o dos por mensaje): qué servicio, cantidad (equipos, km, m2, etc. según la unidad del servicio), ubicación del proyecto, y una descripción breve (tensión, capacidad, fechas, lo que sepa).
3. Pide su nombre y su teléfono (WhatsApp de preferencia). El correo y la empresa son opcionales: pregúntalos una vez, sin insistir. En cuanto tengas nombre y teléfono, usa `registrar_cliente`.
4. Antes de registrar, resume en una lista corta lo que se va a cotizar y pide que lo confirme.
5. Con la confirmación, usa `registrar_cotizacion`. Después dale al cliente: el folio, el presupuesto tal como lo devolvió la herramienta, y que un ingeniero de BOMAR lo contactará para confirmar. Termina diciéndole que si desea otra cotización, puede escribir {PALABRA_CLAVE}.
6. Una sola cotización por folio. Si el cliente pide algo totalmente distinto después de registrar, sugiérele escribir {PALABRA_CLAVE}.

PRECIOS
- Usa ÚNICAMENTE los precios del catálogo. NUNCA inventes precios, descuentos, tiempos de entrega ni garantías.
- El presupuesto oficial lo calcula `registrar_cotizacion`; no hagas cuentas por tu cuenta ni prometas un total antes.
- Si un servicio dice "sin precio publicado", explica que un ingeniero lo cotiza a la medida, y regístralo de todos modos.
- Si el precio es "desde", aclara que es un precio base y que el final depende del proyecto.
- Aclara siempre que el presupuesto es preliminar y que BOMAR lo confirma al revisar el proyecto.

REGLAS
- No inventes servicios, certificaciones, clientes, ubicación, horarios ni datos de la empresa. Si no lo sabes, dilo y ofrece que un ingeniero lo contacte.
- No des instrucciones técnicas que pongan en riesgo a alguien (por ejemplo, intervenir equipo energizado); recomienda la visita de personal calificado.
- Pide solo los datos necesarios (nombre, teléfono, y opcionalmente correo y empresa).
- Responde solo sobre BOMAR y sus servicios; si preguntan otra cosa, redirige con amabilidad.
- Texto plano, sin Markdown (nada de asteriscos, almohadillas ni tablas). Para listas usa guiones.
- Si el cliente tiene prisa o prefiere hablar con alguien, dale el teléfono {TELEFONO} y el correo {CORREO}, y aun así ofrece registrar su solicitud.

CATÁLOGO (usa el ID en las herramientas)
{lineas}

INFORMACIÓN COMPLETA DE BOMAR
{INFO_EMPRESA}
"""


def prompt_cliente(session_id: str) -> str:
    """Parte del prompt que cambia por chat: si ya sabemos quién es el cliente."""
    cliente = db.cliente_de_sesion(session_id)
    if not cliente:
        return "ESTADO DEL CLIENTE\nTodavía no sabes quién es. Pide nombre y teléfono cuando corresponda y usa registrar_cliente."
    folios = db.folios_de_cliente(cliente["id"])
    previas = "\n".join(f"- {f['folio']}: {f['servicio'] or 'sin descripción'} ({f['estado']})" for f in folios) or "- ninguna"
    return f"""ESTADO DEL CLIENTE
Cliente ya identificado y guardado. NO le vuelvas a pedir nombre ni teléfono; cuando confirme, usa registrar_cotizacion directamente.
- Nombre: {cliente['nombre']}
- Teléfono: {cliente['telefono']}
- Correo: {cliente['correo'] or 'no dado'}
- Empresa: {cliente['empresa'] or 'no dada'}
Cotizaciones anteriores de este cliente:
{previas}"""


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

HERRAMIENTAS = [
    {
        "name": "registrar_cliente",
        "description": (
            "Guarda los datos del cliente (se identifica por teléfono) y lo liga a este chat. "
            "Úsala en cuanto tengas su nombre y su teléfono. Si el cliente ya existía, lo reconoce."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del cliente"},
                "telefono": {"type": "string", "description": "Teléfono o WhatsApp (10 dígitos en México)"},
                "correo": {"type": "string", "description": "Correo, si lo dio"},
                "empresa": {"type": "string", "description": "Empresa, si la dio"},
            },
            "required": ["nombre", "telefono"],
        },
    },
    {
        "name": "registrar_cotizacion",
        "description": (
            "Registra la cotización del cliente ya identificado, calcula el presupuesto con los precios del "
            "catálogo, genera el folio y avisa a BOMAR. Úsala solo después de que el cliente confirme lo que quiere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "conceptos": {
                    "type": "array",
                    "description": "Servicios del catálogo que se cotizan",
                    "items": {
                        "type": "object",
                        "properties": {
                            "servicio_id": {"type": "integer", "description": "ID del servicio en el catálogo"},
                            "cantidad": {"type": "number", "description": "Cantidad en la unidad del servicio (mínimo 1)"},
                            "detalle": {"type": "string", "description": "Aclaración corta del concepto (opcional)"},
                        },
                        "required": ["servicio_id", "cantidad"],
                    },
                },
                "servicio": {"type": "string", "description": "Resumen corto de lo que pide (ej. 'Mantenimiento a subestación 115 kV')"},
                "descripcion": {"type": "string", "description": "Descripción del proyecto con todo lo que dijo el cliente"},
                "ubicacion": {"type": "string", "description": "Ciudad o lugar del proyecto"},
            },
            "required": ["conceptos", "servicio", "descripcion"],
        },
    },
]


def ejecutar_registrar_cliente(session_id: str, datos: dict) -> dict:
    nombre = str(datos.get("nombre", "")).strip()[:120]
    telefono = db.normalizar_telefono(str(datos.get("telefono", "")))
    correo = str(datos.get("correo", "") or "").strip()[:120]
    empresa = str(datos.get("empresa", "") or "").strip()[:120]

    if len(nombre) < 2:
        return {"ok": False, "error": "Falta el nombre del cliente."}
    if not 10 <= len(telefono) <= 13:
        return {"ok": False, "error": "El teléfono no parece válido (debe tener 10 dígitos). Pídeselo de nuevo."}
    if correo and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
        return {"ok": False, "error": "El correo no parece válido. Pídeselo de nuevo o continúa sin correo."}

    cliente, es_nuevo = db.registrar_cliente(session_id, nombre, telefono, correo, empresa)
    previas = db.folios_de_cliente(cliente["id"])
    return {
        "ok": True,
        "cliente_nuevo": es_nuevo,
        "mensaje": "Cliente registrado." if es_nuevo else "Cliente que ya había contactado a BOMAR antes; salúdalo como cliente conocido.",
        "cotizaciones_anteriores": [f"{f['folio']}: {f['servicio']}" for f in previas],
    }


def ejecutar_registrar_cotizacion(session_id: str, datos: dict) -> dict:
    cliente = db.cliente_de_sesion(session_id)
    if not cliente:
        return {"ok": False, "error": "Primero registra al cliente con registrar_cliente (nombre y teléfono)."}

    conceptos = datos.get("conceptos") or []
    servicio = str(datos.get("servicio", "")).strip()[:200]
    descripcion = str(datos.get("descripcion", "")).strip()[:2000]
    ubicacion = str(datos.get("ubicacion", "") or "").strip()[:200]
    if not descripcion:
        return {"ok": False, "error": "Falta la descripción del proyecto."}
    if not isinstance(conceptos, list) or not conceptos:
        return {"ok": False, "error": "Indica al menos un servicio del catálogo en 'conceptos'."}

    catalogo = {s["id"]: s for s in db.obtener_catalogo(solo_activos=True)}
    lineas, total, hay_precio, estimado, revision = [], 0.0, False, False, False

    for it in conceptos[:20]:
        try:
            sid = int(it.get("servicio_id"))
            cantidad = float(it.get("cantidad", 1))
        except (TypeError, ValueError, AttributeError):
            return {"ok": False, "error": "Servicio o cantidad inválidos."}
        if cantidad <= 0 or cantidad > 100000:
            return {"ok": False, "error": f"Cantidad inválida para el servicio {sid}."}
        s = catalogo.get(sid)
        if s is None:
            return {"ok": False, "error": f"El servicio con ID {sid} no existe en el catálogo."}

        cant_txt = f"{cantidad:g} {s.get('unidad') or 'servicio'}"
        extra = f" ({str(it.get('detalle')).strip()[:120]})" if it.get("detalle") else ""
        if s["tipo_precio"] == "manual" or s["precio"] is None:
            revision = True
            lineas.append(f"- {s['nombre']}{extra}: {cant_txt} · por cotizar")
        else:
            subtotal = s["precio"] * cantidad
            total += subtotal
            hay_precio = True
            if s["tipo_precio"] == "desde":
                estimado = True
                lineas.append(f"- {s['nombre']}{extra}: {cant_txt} x desde {_dinero(s['precio'])} = desde {_dinero(subtotal)}")
            else:
                lineas.append(f"- {s['nombre']}{extra}: {cant_txt} x {_dinero(s['precio'])} = {_dinero(subtotal)}")

    detalle = "\n".join(lineas)
    total_final = round(total, 2) if hay_precio else None
    sol = db.crear_solicitud(cliente["id"], session_id, servicio, descripcion, ubicacion, detalle,
                             total_final, estimado, revision)

    es_cliente_nuevo = len(db.folios_de_cliente(cliente["id"], limite=2)) == 1
    notificaciones.avisar_nueva_solicitud(sol, cliente, es_cliente_nuevo)

    if total_final is None:
        resumen_total = "Sin precio publicado: un ingeniero de BOMAR enviará el presupuesto."
    else:
        resumen_total = ("Total estimado: desde " if estimado else "Total: ") + _dinero(total_final) + " (más IVA si aplica)"
        if revision:
            resumen_total += ". Algunos conceptos no tienen precio publicado y se cotizan aparte."
    return {
        "ok": True,
        "folio": sol["folio"],
        "detalle": detalle,
        "total": resumen_total,
        "nota": "Presupuesto preliminar. BOMAR lo confirma al revisar el proyecto.",
    }


# ---------------------------------------------------------------------------
# Conversación
# ---------------------------------------------------------------------------

def _a_mensajes_api(historial) -> list[dict]:
    mensajes = []
    for fila in historial:
        rol = "user" if fila["remitente"] == "cliente" else "assistant"
        if mensajes and mensajes[-1]["role"] == rol:
            mensajes[-1]["content"] += "\n" + fila["mensaje"]
        else:
            mensajes.append({"role": rol, "content": fila["mensaje"]})
    while mensajes and mensajes[0]["role"] != "user":
        mensajes.pop(0)
    return mensajes


def _limpiar_markdown(texto: str) -> str:
    lineas = []
    for linea in texto.replace("**", "").replace("__", "").splitlines():
        sin_espacios = linea.lstrip()
        if sin_espacios.startswith("#"):
            linea = sin_espacios.lstrip("#").strip()
        elif sin_espacios.startswith("* "):
            linea = linea.replace("* ", "- ", 1)
        lineas.append(linea)
    return "\n".join(lineas).strip()


def _respuesta_nueva_cotizacion(session_id: str) -> str:
    db.marcar_corte(session_id)
    cliente = db.cliente_de_sesion(session_id)
    if cliente:
        nombre = cliente["nombre"].split()[0]
        return (f"Perfecto, {nombre}. Empezamos una cotización nueva; sus datos y sus cotizaciones anteriores "
                f"quedan guardados. ¿Qué servicio necesita esta vez?")
    return "Perfecto, empezamos una cotización nueva desde cero. ¿Qué servicio necesita?"


def responder(client, session_id: str, texto_cliente: str) -> str:
    texto_cliente = texto_cliente.strip()[:MAX_MENSAJE]
    db.asegurar_sesion(session_id)
    db.guardar_mensaje(session_id, "cliente", texto_cliente)

    # Palabra clave: no gasta API, solo reinicia el contexto del bot.
    if es_palabra_clave(texto_cliente):
        respuesta = _respuesta_nueva_cotizacion(session_id)
        db.guardar_mensaje(session_id, "bot", respuesta)
        return respuesta

    mensajes = _a_mensajes_api(db.historial_para_ia(session_id))
    sistema = [
        {"type": "text", "text": prompt_fijo(db.obtener_catalogo(solo_activos=True)),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": prompt_cliente(session_id)},
    ]

    texto_final = ""
    for _ in range(MAX_VUELTAS_TOOL):
        resp = client.messages.create(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=sistema,
            tools=HERRAMIENTAS,
            messages=mensajes,
        )
        texto_final = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason != "tool_use":
            break

        mensajes.append({"role": "assistant", "content": resp.content})
        resultados = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                if b.name == "registrar_cliente":
                    salida = ejecutar_registrar_cliente(session_id, b.input)
                elif b.name == "registrar_cotizacion":
                    salida = ejecutar_registrar_cotizacion(session_id, b.input)
                else:
                    salida = {"ok": False, "error": "Herramienta desconocida."}
            except Exception as e:
                print(f"[ERROR] herramienta {b.name}: {e!r}")
                salida = {"ok": False, "error": "Error interno al guardar; ofrece al cliente el teléfono de BOMAR."}
            resultados.append({
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": json.dumps(salida, ensure_ascii=False),
            })
        mensajes.append({"role": "user", "content": resultados})
        # Después de registrar al cliente, el prompt debe reflejarlo
        sistema[1] = {"type": "text", "text": prompt_cliente(session_id)}

    texto_final = _limpiar_markdown(texto_final)
    if not texto_final:
        texto_final = (
            "Lo siento, no pude generar una respuesta. Puede intentar de nuevo, escribirnos a "
            f"{CORREO} o llamarnos al {TELEFONO}."
        )

    db.guardar_mensaje(session_id, "bot", texto_final)
    return texto_final
