"""
BOMAR Bot - Lógica del asistente (sin FastAPI)

Flujo de una cotización:
  1. El bot entiende qué necesita el cliente y le explica los servicios.
  2. Le pide nombre y teléfono -> herramienta `registrar_cliente`
     (el cliente queda guardado por su teléfono; si ya existía, se reconoce).
  3. Confirma los conceptos -> herramienta `registrar_cotizacion`
     (genera la pre-cotización con folio BOM-0001, calcula un rango aproximado
     si el servicio tiene uno, y le avisa por correo al dueño).
     La cotización real y final la hace el dueño al comunicarse con el cliente,
     porque el precio depende del servicio, el lugar, la distancia, etc.
  4. Si el cliente escribe NUEVA COTIZACIÓN (o usa el botón), el bot empieza
     una cotización desde cero en el mismo chat, sin volver a pedirle sus datos.

Regla importante: los rangos aproximados los calcula este código, nunca la IA.
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


_SI = ("si", "sí", "correcto", "correctos", "es correcto", "son correctos", "confirmo", "confirmado", "asi es",
       "ok", "okay", "va", "claro", "afirmativo", "exacto", "todo bien", "esta bien", "de acuerdo", "adelante",
       "perfecto", "listo", "registralo", "registrala", "procede")
_NO = re.compile(r"\b(no|pero|espera|mal|incorrect\w*|corrig\w*|correg\w*|cambi\w*|equivoc\w*|error\w*|otro)\b")


def es_confirmacion(texto: str) -> bool:
    """True si el mensaje del cliente es un 'sí' claro, sin correcciones."""
    t = re.sub(r"[^a-z0-9 ]", " ", _sin_acentos(texto.lower()))
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) > 80:
        return False
    if _NO.search(t):
        return False
    return any(t == x or t.startswith(x + " ") for x in (_sin_acentos(y) for y in _SI))


def validar_telefono(original: str):
    """Devuelve (telefono_normalizado, error)."""
    crudo = (original or "").strip()
    tel = db.normalizar_telefono(crudo)
    extranjero = crudo.startswith("+") and not crudo.replace(" ", "").startswith("+52")
    if extranjero:
        if not 8 <= len(tel) <= 15:
            return None, "El teléfono internacional no parece válido. Pídeselo de nuevo con lada de país."
        return tel, None
    if len(tel) != 10:
        return None, (f"El teléfono tiene {len(tel)} dígitos y en México deben ser 10 (lada + número). "
                      "Dile cuántos dígitos tiene el que escribió y pídele que lo revise.")
    if tel[0] in "01":
        return None, "Ese teléfono no parece válido (en México no empieza con 0 ni 1). Pídele que lo revise."
    if len(set(tel)) <= 2 or tel in "01234567890123456789" or tel in "98765432109876543210":
        return None, "Ese teléfono parece de prueba o falso (dígitos repetidos o seguidos). Pídele su número real."
    return tel, None


def telefono_bonito(tel: str) -> str:
    return f"{tel[:2]} {tel[2:6]} {tel[6:]}" if len(tel) == 10 else tel


def _dinero(v):
    return f"${v:,.2f} MXN"


def _rango(s: dict):
    """(mínimo, máximo) aproximados por unidad, o None si el servicio no tiene precio."""
    if s["tipo_precio"] == "manual" or s["precio"] is None:
        return None
    minimo = s["precio"]
    maximo = s.get("precio_max") or minimo
    return minimo, max(minimo, maximo)


def _rango_texto(minimo, maximo):
    return _dinero(minimo) if maximo == minimo else f"{_dinero(minimo)} a {_dinero(maximo)}"


def _precio_texto(s: dict) -> str:
    r = _rango(s)
    if r is None:
        return "sin precio aproximado: lo cotiza directamente BOMAR"
    return f"aproximado de {_rango_texto(*r)} por {s.get('unidad') or 'servicio'} (referencia, no es precio final)"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def prompt_fijo(catalogo: list[dict]) -> str:
    """Parte del prompt que casi no cambia (se guarda en caché para ahorrar)."""
    lineas = "\n".join(
        f"- ID {s['id']}: {s['nombre']} — {s['descripcion'] or ''} | Aproximado: {_precio_texto(s)}"
        for s in catalogo
    ) or "(sin servicios registrados)"

    return f"""Eres el asistente virtual de BOMAR, empresa mexicana de construcción, ingeniería y consultoría para proyectos energéticos, industriales y residenciales. Atiendes a los visitantes de bomar.mx por chat, en español, con tono profesional, cordial y breve (máximo 5-6 líneas por respuesta, salvo que el cliente pida detalle). Hablas de "usted" salvo que el cliente tutee.

TU OBJETIVO
Que cada cliente deje una pre-cotización completa y bien explicada, para que el dueño de BOMAR la revise en su panel, se comunique con el cliente y le dé la cotización real y final.

CÓMO ATENDER
1. Entiende qué necesita el cliente. Explícale qué servicio de BOMAR le sirve, usando solo la información de abajo.
2. Reúne lo que el dueño necesita para cotizar, con preguntas cortas (una o dos por mensaje): qué servicio, cantidad o tamaño (equipos, km, m2, kVA, etc.), ubicación exacta del proyecto (ciudad y lugar), una descripción del alcance (tensión, capacidad, estado actual del equipo) y para cuándo lo necesita.
3. Pide su nombre y su teléfono (WhatsApp de preferencia, 10 dígitos). El correo y la empresa son opcionales: pregúntalos una vez, sin insistir.
4. CONFIRMACIÓN DE DATOS (obligatoria): antes de registrar, muéstrale sus datos en una lista, con el teléfono en formato 81 1234 5678:
   - Nombre: ...
   - Teléfono: ...
   - Correo: ... (si lo dio)
   - Empresa: ... (si la dio)
   y pregunta exactamente: ¿Son correctos estos datos?
   Solo cuando responda que sí, usa `registrar_cliente`. Si corrige algo, vuelve a mostrar los datos corregidos y pregunta otra vez.
5. CONFIRMACIÓN DE LA SOLICITUD (obligatoria): resume en una lista lo que se va a cotizar (servicio, cantidad, ubicación, descripción) y pregunta exactamente: ¿Confirma que registre esta solicitud?
   Puedes pedir ambas confirmaciones en el mismo mensaje si ya tienes todo. Solo cuando responda que sí, usa `registrar_cotizacion`.
6. Después de registrar, dale al cliente: el folio, el resumen de su solicitud, el aproximado SOLO si la herramienta lo devolvió, y explícale que el dueño de BOMAR se comunicará con él para darle la cotización real y final. Termina diciéndole que si desea otra cotización, puede escribir {PALABRA_CLAVE}.
7. Una sola cotización por folio. Si el cliente pide algo totalmente distinto después de registrar, sugiérele escribir {PALABRA_CLAVE}.

PRECIOS (MUY IMPORTANTE)
- Los precios de BOMAR varían mucho según el servicio, el lugar, la distancia y el alcance del proyecto. Por eso el chat NUNCA da una cotización final.
- La cotización real y final siempre la da el dueño de BOMAR cuando se comunica con el cliente. Dilo con claridad.
- Solo menciona cifras si `registrar_cotizacion` devolvió un aproximado, y preséntalo como "aproximado de referencia". No hagas cuentas por tu cuenta ni des cifras antes de registrar.
- Si un servicio no tiene aproximado, no des ninguna cifra ni rango: explica que BOMAR cotiza según el proyecto.
- Si el cliente insiste en un precio, explica amablemente por qué depende del proyecto y que el dueño lo contactará pronto con la cotización exacta.
- NUNCA inventes precios, descuentos, tiempos de entrega ni garantías.

VALIDACIÓN Y CORRECCIONES
- Si una herramienta responde que el teléfono o el correo no son válidos, explícale al cliente qué está mal (por ejemplo, cuántos dígitos tiene) y pídeselo de nuevo con amabilidad.
- Si una herramienta responde requiere_confirmacion, todavía no se guardó nada: muestra los datos o el resumen y pide la confirmación.
- Si después de registrar el cliente dice que algún dato estaba mal, muéstrale el dato corregido, pide confirmación y vuelve a usar `registrar_cliente`: el sistema corrige el mismo registro.

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
            "Registra la pre-cotización del cliente ya identificado, genera el folio, calcula un aproximado de "
            "referencia si el servicio lo tiene y avisa al dueño de BOMAR, quien dará la cotización final. "
            "Úsala solo después de que el cliente confirme lo que quiere."
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
    nombre = re.sub(r"\s+", " ", str(datos.get("nombre", ""))).strip()[:120]
    correo = str(datos.get("correo", "") or "").strip().lower()[:120]
    empresa = str(datos.get("empresa", "") or "").strip()[:120]

    if len(nombre) < 2 or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", nombre):
        return {"ok": False, "error": "Falta el nombre del cliente o no parece un nombre. Pídeselo."}
    telefono, error = validar_telefono(str(datos.get("telefono", "")))
    if error:
        return {"ok": False, "error": error}
    if correo and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", correo):
        return {"ok": False, "error": "El correo no parece válido. Pídeselo de nuevo, o continúa sin correo si no quiere darlo."}

    # Confirmación obligatoria: el cliente tuvo que ver sus datos y decir que sí
    ultimo_cliente, ultimo_bot = db.ultimo_intercambio(session_id)
    mostro_telefono = telefono in re.sub(r"\D", "", ultimo_bot)
    if not (mostro_telefono and es_confirmacion(ultimo_cliente)):
        return {
            "ok": False,
            "requiere_confirmacion": True,
            "error": ("Todavía NO está registrado. Primero muéstrale sus datos tal como los vas a guardar y pregúntale "
                      "exactamente: ¿Son correctos estos datos? Regístralo solo cuando responda que sí."),
            "datos_a_confirmar": {
                "nombre": nombre,
                "telefono": telefono_bonito(telefono),
                "correo": correo or "(no dio)",
                "empresa": empresa or "(no dio)",
            },
        }

    cliente, es_nuevo, fue_correccion = db.registrar_cliente(session_id, nombre, telefono, correo, empresa)
    previas = db.folios_de_cliente(cliente["id"])
    if fue_correccion:
        mensaje = "Datos corregidos en el mismo cliente (no se creó otro). Confírmale que ya quedaron bien."
        if previas:
            notificaciones.avisar_correccion(cliente, previas)
    elif es_nuevo:
        mensaje = "Cliente registrado."
    else:
        mensaje = "Cliente que ya había contactado a BOMAR antes; salúdalo como cliente conocido."
    return {
        "ok": True,
        "cliente_nuevo": es_nuevo,
        "correccion": fue_correccion,
        "mensaje": mensaje,
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

    ultimo_cliente, _ = db.ultimo_intercambio(session_id)
    if not es_confirmacion(ultimo_cliente):
        return {
            "ok": False,
            "requiere_confirmacion": True,
            "error": ("Todavía NO está registrada. Muéstrale el resumen de la solicitud (servicio, cantidad, ubicación, "
                      "descripción) y pregúntale exactamente: ¿Confirma que registre esta solicitud? "
                      "Regístrala solo cuando responda que sí."),
        }

    catalogo = {s["id"]: s for s in db.obtener_catalogo(solo_activos=True)}
    lineas, tot_min, tot_max, hay_precio, revision = [], 0.0, 0.0, False, False

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
        r = _rango(s)
        if r is None:
            revision = True
            lineas.append(f"- {s['nombre']}{extra}: {cant_txt} · lo cotiza BOMAR")
        else:
            hay_precio = True
            tot_min += r[0] * cantidad
            tot_max += r[1] * cantidad
            lineas.append(f"- {s['nombre']}{extra}: {cant_txt} · aprox. {_rango_texto(r[0] * cantidad, r[1] * cantidad)}")

    detalle = "\n".join(lineas)
    total_min = round(tot_min, 2) if hay_precio else None
    total_max = round(tot_max, 2) if hay_precio else None
    sol = db.crear_solicitud(cliente["id"], session_id, servicio, descripcion, ubicacion, detalle,
                             total_min, total_max, revision)

    es_cliente_nuevo = len(db.folios_de_cliente(cliente["id"], limite=2)) == 1
    notificaciones.avisar_nueva_solicitud(sol, cliente, es_cliente_nuevo)

    if total_min is None:
        aproximado = "Sin aproximado: no des cifras. El dueño de BOMAR le dará la cotización al comunicarse."
    else:
        aproximado = "Aproximado de referencia: " + _rango_texto(total_min, total_max) + " más IVA"
        if revision:
            aproximado += ", sin contar los conceptos que cotiza BOMAR directamente"
    return {
        "ok": True,
        "folio": sol["folio"],
        "detalle": detalle,
        "aproximado": aproximado,
        "nota": ("No es la cotización final. El precio depende del servicio, el lugar, la distancia y el alcance; "
                 "el dueño de BOMAR se comunicará con el cliente para darle la cotización real y final."),
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
