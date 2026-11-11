"""
BOMAR Bot - Lógica del asistente (sin FastAPI)

Es la misma idea que el bot de GECTAM, con una diferencia importante:
BOMAR no tiene precios fijos (son servicios de ingeniería que se cotizan
según cada proyecto). Por eso el bot NO da precios: explica los servicios,
resuelve dudas y, cuando el cliente quiere una cotización o asesoría,
registra la solicitud con la herramienta `registrar_solicitud` para que
una persona de BOMAR lo contacte.
"""

import json
import os

import database as db
from bomar_info import CORREO, INFO_EMPRESA, TELEFONO

MODELO = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = 700
MAX_MENSAJE = 1000      # caracteres máximos por mensaje del cliente
MAX_VUELTAS_TOOL = 4    # evita ciclos infinitos con herramientas


def construir_prompt_sistema(catalogo: list[dict]) -> str:
    areas = "\n".join(f"- {s['nombre']}: {s['descripcion'] or ''}" for s in catalogo) or "(sin áreas registradas)"

    return f"""Eres el asistente virtual de BOMAR, empresa mexicana de construcción, ingeniería y consultoría para proyectos energéticos, industriales y residenciales. Atiendes a visitantes de bomar.mx por chat, en español, con un tono profesional, amable y breve (máximo 4-5 líneas por respuesta, salvo que el cliente pida detalle).

TU TRABAJO
1. Entender qué necesita el cliente y explicarle qué servicios de BOMAR le sirven, usando solo la información de abajo.
2. Resolver dudas generales sobre los servicios.
3. Cuando el cliente quiera una cotización, una visita o una asesoría personalizada, pídele estos datos, uno o dos a la vez y de forma natural:
   - nombre
   - teléfono o correo
   - empresa (opcional)
   - qué servicio necesita y una breve descripción del proyecto (ubicación, tensión, tamaño, fechas, lo que sepa)
4. Con nombre, contacto y descripción, usa la herramienta `registrar_solicitud`. Después confírmale que un ingeniero de BOMAR lo contactará, y dale también el teléfono {TELEFONO} y el correo {CORREO} por si quiere adelantar.

ÁREAS DE SERVICIO
{areas}

INFORMACIÓN COMPLETA DE BOMAR
{INFO_EMPRESA}

REGLAS ESTRICTAS
- BOMAR no tiene precios publicados. NUNCA des precios, rangos, estimados, descuentos, tiempos de entrega ni garantías que no estén arriba. Si preguntan cuánto cuesta, explica que cada proyecto se cotiza a la medida y ofrece registrar su solicitud.
- No inventes servicios, certificaciones, clientes, ubicación, horarios ni datos de la empresa. Si no está en la información de arriba, dilo con honestidad y ofrece que un ingeniero lo contacte.
- No des asesoría técnica que ponga en riesgo a alguien (por ejemplo, cómo intervenir equipo energizado). Para eso, recomienda la visita de personal calificado.
- Pide solo los datos personales necesarios (nombre, contacto, empresa).
- Responde solo sobre BOMAR y sus servicios; si preguntan otra cosa, redirige con amabilidad.
- Escribe en texto plano: no uses Markdown (nada de asteriscos, almohadillas ni tablas). Para listas usa guiones simples.
"""


HERRAMIENTAS = [
    {
        "name": "registrar_solicitud",
        "description": (
            "Registra una solicitud de cotización o asesoría para que un ingeniero de BOMAR "
            "contacte al cliente. Úsala solo cuando ya tengas el nombre, un medio de contacto "
            "y una descripción de lo que necesita."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente_nombre": {"type": "string", "description": "Nombre del cliente"},
                "cliente_contacto": {"type": "string", "description": "Teléfono o correo del cliente"},
                "empresa": {"type": "string", "description": "Empresa del cliente, si la dio"},
                "servicio": {"type": "string", "description": "Área o servicio de BOMAR que le interesa"},
                "descripcion": {"type": "string", "description": "Resumen del proyecto o necesidad del cliente"},
            },
            "required": ["cliente_nombre", "cliente_contacto", "descripcion"],
        },
    }
]


def ejecutar_registrar_solicitud(session_id: str, datos: dict) -> dict:
    """Valida y guarda la solicitud. Devuelve un dict que se le regresa a la IA."""
    nombre = str(datos.get("cliente_nombre", "")).strip()[:120]
    contacto = str(datos.get("cliente_contacto", "")).strip()[:120]
    empresa = str(datos.get("empresa", "") or "").strip()[:120]
    servicio = str(datos.get("servicio", "") or "").strip()[:200]
    descripcion = str(datos.get("descripcion", "")).strip()[:1500]

    if not nombre or not contacto:
        return {"ok": False, "error": "Faltan el nombre o el contacto del cliente. Pídeselos."}
    if not descripcion:
        return {"ok": False, "error": "Falta la descripción de lo que necesita el cliente."}

    resumen = "\n".join(
        linea for linea in [
            f"Empresa: {empresa}" if empresa else "",
            f"Servicio: {servicio}" if servicio else "",
            f"Necesidad: {descripcion}",
        ] if linea
    )
    db.guardar_cotizacion(session_id, nombre, contacto, resumen, None)
    return {"ok": True, "mensaje": "Solicitud registrada. Un ingeniero de BOMAR contactará al cliente."}


def _a_mensajes_api(historial) -> list[dict]:
    """Convierte el historial de la BD al formato de la API (roles alternados)."""
    mensajes = []
    for fila in historial:
        rol = "user" if fila["remitente"] == "cliente" else "assistant"
        if mensajes and mensajes[-1]["role"] == rol:
            mensajes[-1]["content"] += "\n" + fila["mensaje"]
        else:
            mensajes.append({"role": rol, "content": fila["mensaje"]})
    # la API exige que el primer mensaje sea del usuario
    while mensajes and mensajes[0]["role"] != "user":
        mensajes.pop(0)
    return mensajes


def _limpiar_markdown(texto: str) -> str:
    """Quita los asteriscos y almohadillas que a veces pone el modelo."""
    lineas = []
    for linea in texto.replace("**", "").replace("__", "").splitlines():
        sin_espacios = linea.lstrip()
        if sin_espacios.startswith("#"):
            linea = sin_espacios.lstrip("#").strip()
        elif sin_espacios.startswith("* "):
            linea = linea.replace("* ", "- ", 1)
        lineas.append(linea)
    return "\n".join(lineas).strip()


def responder(client, session_id: str, texto_cliente: str) -> str:
    """
    Flujo completo de un turno de chat:
    guarda el mensaje, llama a Claude (con historial y herramientas),
    ejecuta herramientas si hace falta, guarda y devuelve la respuesta.
    """
    texto_cliente = texto_cliente.strip()[:MAX_MENSAJE]
    db.guardar_mensaje(session_id, "cliente", texto_cliente)

    mensajes = _a_mensajes_api(db.obtener_historial(session_id, limite=20))
    sistema = construir_prompt_sistema(db.obtener_catalogo())

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
            if b.type == "tool_use":
                if b.name == "registrar_solicitud":
                    salida = ejecutar_registrar_solicitud(session_id, b.input)
                else:
                    salida = {"ok": False, "error": "Herramienta desconocida."}
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": json.dumps(salida, ensure_ascii=False),
                })
        mensajes.append({"role": "user", "content": resultados})

    texto_final = _limpiar_markdown(texto_final)
    if not texto_final:
        texto_final = (
            "Lo siento, no pude generar una respuesta. Puedes intentar de nuevo o escribirnos a "
            f"{CORREO} / llamarnos al {TELEFONO}."
        )

    db.guardar_mensaje(session_id, "bot", texto_final)
    return texto_final
