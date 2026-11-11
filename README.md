# BOMAR Bot

Asistente de chat con IA (API de Claude) para bomar.mx. Es una copia adaptada del bot de GECTAM.

Qué hace:
- Explica los servicios de BOMAR (los saca de `backend/bomar_info.py`).
- No da precios: cuando el cliente quiere cotización, le pide nombre, contacto y descripción del proyecto, y guarda la solicitud.
- Panel de administrador en `/admin` para ver conversaciones y solicitudes.
- El mismo servidor entrega el chat en `/widget.js`.

## Estructura

```
bomar-bot/
└── backend/
    ├── main.py          # API (FastAPI): /chat, /widget.js, /admin
    ├── cotizador.py     # lo que "piensa" el bot (prompt + herramienta registrar_solicitud)
    ├── bomar_info.py    # toda la información de BOMAR (servicios, teléfono, correo)
    ├── database.py      # SQLite: servicios, conversaciones, solicitudes
    ├── requirements.txt
    ├── .env.example
    └── static/
        ├── widget.js    # burbuja de chat
        ├── admin.html   # panel de administrador
        └── styles.css
```

## Variables de entorno (en Render)

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic |
| `ADMIN_PASSWORD` | contraseña del panel `/admin` |
| `ANTHROPIC_MODEL` | opcional, por defecto `claude-sonnet-5-5` |
| `ALLOWED_ORIGINS` | opcional, por defecto `https://bomar.mx,https://www.bomar.mx` |

## Render

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## WordPress (Divi)

Divi → Opciones del tema → Integración → "Añadir código al final de <body>":

```html
<script src="https://bomar-bot.onrender.com/widget.js" defer></script>
```

Cualquier botón del sitio puede abrir el chat si tiene el atributo `data-open-chat`.

## Cambiar la información de BOMAR

Edita `backend/bomar_info.py`, guarda, haz commit y push. Render vuelve a desplegar solo.
