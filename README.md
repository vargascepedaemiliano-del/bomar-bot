# BOMAR Bot

Asistente de chat con IA (API de Claude) para bomar.mx. Atiende a los clientes, les arma un presupuesto con los precios del catálogo y deja todo ordenado en un panel para el dueño.

## Qué hace

- Explica los servicios de BOMAR (`backend/bomar_info.py`).
- Registra a cada cliente por **nombre y teléfono**; si regresa, lo reconoce.
- Arma la cotización con folio (`BOM-0001`) y calcula el presupuesto con los precios que se cargan en el panel. Los servicios sin precio quedan "por cotizar".
- Avisa por **correo** al dueño en cuanto llega una cotización.
- Palabra clave **NUEVA COTIZACIÓN** (o el botón del chat): empieza otra cotización en el mismo chat sin volver a pedir datos.
- Panel en `/admin` (funciona en celular): cotizaciones con estado y notas, clientes con todas sus cotizaciones, conversaciones, servicios y precios, exportar a Excel (CSV).
- Límite anti-abuso por IP y por conversación, y caché de prompts para bajar el costo de la API.

## Estructura

```
backend/
├── main.py            # API (FastAPI): /chat, /widget.js, /admin y API del panel
├── cotizador.py       # lógica del bot: prompt, herramientas, palabra clave
├── database.py        # SQLite: servicios, clientes, sesiones, conversaciones, solicitudes
├── notificaciones.py  # correo al dueño (SMTP)
├── bomar_info.py      # información de la empresa
├── requirements.txt
├── .env.example       # todas las variables, explicadas
└── static/
    ├── widget.js      # burbuja de chat
    └── admin.html     # panel del dueño
```

## Render

- Plan: Starter (siempre encendido) + **Disk** de 1 GB montado en `/var/data`
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Variables: ver `backend/.env.example` (mínimo `ANTHROPIC_API_KEY`, `ADMIN_PASSWORD`, `DB_PATH`)

## WordPress (Divi)

Divi → Opciones del tema → Integración → "Agregar código al <body>":

```html
<script src="https://bomar-bot.onrender.com/widget.js" defer></script>
```

## Precios

Se cargan en el panel → **Servicios y precios**. Tipos: sin precio (lo cotiza un ingeniero), precio fijo, o precio "desde". El bot los usa de inmediato.
