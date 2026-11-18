"""
BOMAR Bot - Aviso por correo al dueño cuando llega una cotización

Se configura con variables de entorno en Render:
  SMTP_HOST      servidor de correo   (Gmail: smtp.gmail.com  /  Hostinger: smtp.hostinger.com)
  SMTP_PORT      465 (SSL) o 587 (STARTTLS)
  SMTP_USER      correo que envía
  SMTP_PASSWORD  contraseña (en Gmail: "contraseña de aplicación", no la normal)
  NOTIFY_TO      a quién le llega (puede ser varios separados por coma)
  PANEL_URL      dirección del panel, para poner el enlace en el correo

Si falta alguna, simplemente no se manda correo (el bot sigue funcionando).
El envío se hace en segundo plano para no hacer esperar al cliente.
"""

import html
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage


def _config():
    cfg = {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "465") or 465),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "to": [d.strip() for d in os.getenv("NOTIFY_TO", "").split(",") if d.strip()],
        "panel": os.getenv("PANEL_URL", "").strip(),
    }
    cfg["activo"] = bool(cfg["host"] and cfg["user"] and cfg["password"] and cfg["to"])
    return cfg


def correo_configurado() -> bool:
    return _config()["activo"]


def _dinero(v):
    return "Por cotizar" if v is None else f"${v:,.2f} MXN"


def _construir(sol: dict, cliente: dict, es_cliente_nuevo: bool, cfg: dict) -> EmailMessage:
    tel = cliente["telefono"]
    wa = f"https://wa.me/52{tel}" if len(tel) == 10 else f"https://wa.me/{tel}"
    total_txt = _dinero(sol.get("total"))
    if sol.get("total") is not None and sol.get("total_es_estimado"):
        total_txt += " (estimado, incluye precios 'desde')"
    if sol.get("requiere_revision"):
        total_txt += " · Hay conceptos sin precio: requiere tu cotización"

    filas = [
        ("Folio", sol["folio"]),
        ("Cliente", f"{cliente['nombre']}" + ("" if es_cliente_nuevo else "  (cliente recurrente)")),
        ("Teléfono", tel),
        ("Correo", cliente.get("correo") or "—"),
        ("Empresa", cliente.get("empresa") or "—"),
        ("Servicio", sol.get("servicio") or "—"),
        ("Ubicación", sol.get("ubicacion") or "—"),
        ("Descripción", sol.get("descripcion") or "—"),
        ("Presupuesto", (sol.get("detalle") or "—")),
        ("Total", total_txt),
    ]

    texto = "Nueva solicitud de cotización desde el chat de bomar.mx\n\n" + "\n".join(
        f"{k}: {v}" for k, v in filas
    )
    texto += f"\n\nLlamar: tel:{tel}\nWhatsApp: {wa}"
    if cfg["panel"]:
        texto += f"\nPanel: {cfg['panel']}"

    celdas = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#4a5a75;vertical-align:top;white-space:nowrap"><b>{html.escape(k)}</b></td>'
        f'<td style="padding:6px 0;white-space:pre-wrap">{html.escape(str(v))}</td></tr>'
        for k, v in filas
    )
    boton = lambda url, txt, color: (
        f'<a href="{html.escape(url)}" style="display:inline-block;margin:4px 8px 4px 0;padding:10px 16px;'
        f'background:{color};color:#fff;text-decoration:none;border-radius:8px;font-weight:bold">{txt}</a>'
    )
    botones = boton(f"tel:{tel}", "Llamar", "#043074") + boton(wa, "WhatsApp", "#1f9d55")
    if cliente.get("correo"):
        botones += boton(f"mailto:{cliente['correo']}?subject=Cotización {sol['folio']} - BOMAR", "Responder por correo", "#28508f")
    if cfg["panel"]:
        botones += boton(cfg["panel"], "Abrir panel", "#ed1c24")

    cuerpo_html = f"""<div style="font-family:Arial,Helvetica,sans-serif;color:#0f1d33;max-width:620px">
      <div style="background:#043074;color:#fff;padding:16px 20px;border-radius:10px 10px 0 0">
        <div style="font-size:13px;opacity:.8">Chat de bomar.mx</div>
        <div style="font-size:20px;font-weight:bold">Nueva cotización {html.escape(sol['folio'])}</div>
      </div>
      <div style="border:1px solid #cfd8e6;border-top:0;padding:16px 20px;border-radius:0 0 10px 10px">
        <table style="border-collapse:collapse;font-size:15px">{celdas}</table>
        <div style="margin-top:14px">{botones}</div>
      </div></div>"""

    msg = EmailMessage()
    msg["Subject"] = f"Nueva cotización {sol['folio']} · {cliente['nombre']} · {sol.get('servicio') or 'BOMAR'}"
    msg["From"] = f"Chat BOMAR <{cfg['user']}>"
    msg["To"] = ", ".join(cfg["to"])
    if cliente.get("correo"):
        msg["Reply-To"] = cliente["correo"]
    msg.set_content(texto)
    msg.add_alternative(cuerpo_html, subtype="html")
    return msg


def _enviar(msg: EmailMessage, cfg: dict):
    try:
        _enviar_o_fallar(msg, cfg)
        print(f"[CORREO] Aviso enviado: {msg['Subject']}")
    except Exception as e:
        print(f"[CORREO] No se pudo enviar el aviso: {e!r}")


def avisar_nueva_solicitud(sol: dict, cliente: dict, es_cliente_nuevo: bool):
    cfg = _config()
    if not cfg["activo"]:
        print("[CORREO] Sin configurar (faltan variables SMTP_*/NOTIFY_TO); no se envía aviso.")
        return
    msg = _construir(sol, cliente, es_cliente_nuevo, cfg)
    threading.Thread(target=_enviar, args=(msg, cfg), daemon=True).start()


def enviar_prueba():
    """Manda un correo de prueba de forma síncrona. Devuelve (ok, mensaje)."""
    cfg = _config()
    if not cfg["activo"]:
        return False, "Faltan variables de correo en Render (SMTP_HOST, SMTP_USER, SMTP_PASSWORD, NOTIFY_TO)."
    msg = EmailMessage()
    msg["Subject"] = "Prueba de avisos · Chat BOMAR"
    msg["From"] = f"Chat BOMAR <{cfg['user']}>"
    msg["To"] = ", ".join(cfg["to"])
    msg.set_content("Si recibes este correo, los avisos de nuevas cotizaciones del chat de bomar.mx están funcionando.")
    try:
        _enviar_o_fallar(msg, cfg)
        return True, f"Correo de prueba enviado a {', '.join(cfg['to'])}."
    except Exception as e:
        return False, f"No se pudo enviar: {e}"


def _enviar_o_fallar(msg, cfg):
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ssl.create_default_context(), timeout=20) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
