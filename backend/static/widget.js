/*
 * BOMAR - Widget de chat (burbuja flotante)
 *
 * Para usarlo en WordPress (Divi → Opciones del tema → Integración) basta con pegar:
 *   <script src="https://bomar-bot.onrender.com/widget.js" defer></script>
 * El widget toma la dirección del servidor de su propio src.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var BACKEND = (script && script.getAttribute("data-backend")) ||
    (script && script.src ? new URL(script.src).origin : "https://bomar-bot.onrender.com");

  /* ---------- Estilos (con prefijo gc- para no chocar con la página) ---------- */
  var css = [
    ".gc-root{--tinta:#043074;--tinta2:#28508f;--papel:#f3f6fb;--linea:#cfd8e6;--senal:#ed1c24;font-family:Montserrat,Helvetica,Arial,sans-serif;}",
    ".gc-root *{box-sizing:border-box}",
    ".gc-fab{position:fixed;right:20px;bottom:20px;z-index:99998;display:flex;align-items:center;gap:10px;border:0;cursor:pointer;background:var(--senal);color:#fff;font:600 15px/1 inherit;font-family:inherit;padding:14px 18px 14px 16px;border-radius:999px;box-shadow:0 6px 20px rgba(4,48,116,.3)}",
    ".gc-fab:hover{background:#c8141b}",
    ".gc-fab:focus-visible,.gc-send:focus-visible,.gc-close:focus-visible,.gc-chip:focus-visible{outline:3px solid var(--tinta);outline-offset:2px}",
    ".gc-fab svg{width:22px;height:22px;flex:none}",
    ".gc-panel{position:fixed;right:20px;bottom:20px;z-index:99999;width:380px;max-width:calc(100vw - 24px);height:560px;max-height:calc(100vh - 24px);display:none;flex-direction:column;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 18px 50px rgba(4,48,116,.35);border:1px solid var(--linea)}",
    ".gc-panel.gc-open{display:flex}",
    ".gc-head{background:var(--tinta);color:#fff;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:10px}",
    ".gc-title{font-weight:700;font-size:16px;line-height:1.2}",
    ".gc-sub{font-size:12.5px;opacity:.75;margin-top:2px}",
    ".gc-close{background:transparent;border:0;color:#fff;cursor:pointer;font-size:26px;line-height:1;padding:4px 8px;border-radius:8px}",
    ".gc-close:hover{background:rgba(255,255,255,.12)}",
    ".gc-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:9px;background:var(--papel)}",
    ".gc-msg{max-width:85%;padding:9px 13px;border-radius:14px;font-size:14.5px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}",
    ".gc-bot{background:#fff;color:var(--tinta);align-self:flex-start;border:1px solid var(--linea);border-bottom-left-radius:4px}",
    ".gc-user{background:var(--tinta);color:#fff;align-self:flex-end;border-bottom-right-radius:4px}",
    ".gc-note{align-self:flex-start;font-size:12.5px;color:var(--tinta2);padding:0 4px}",
    ".gc-chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:2px}",
    ".gc-chip{font:inherit;font-size:13.5px;background:#fff;color:var(--tinta);border:1px solid var(--tinta2);border-radius:999px;padding:7px 12px;cursor:pointer}",
    ".gc-chip:hover{background:var(--tinta);color:#fff}",
    ".gc-typing{display:inline-flex;gap:4px;padding:12px 14px}",
    ".gc-typing i{width:7px;height:7px;border-radius:50%;background:var(--tinta2);opacity:.35;animation:gc-b 1.1s infinite}",
    ".gc-typing i:nth-child(2){animation-delay:.18s}.gc-typing i:nth-child(3){animation-delay:.36s}",
    "@keyframes gc-b{0%,80%,100%{opacity:.25;transform:translateY(0)}40%{opacity:1;transform:translateY(-3px)}}",
    ".gc-form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--linea);background:#fff}",
    ".gc-input{flex:1;font:inherit;font-size:15px;border:1px solid var(--linea);border-radius:10px;padding:10px 12px;color:var(--tinta);min-width:0}",
    ".gc-input:focus{outline:2px solid var(--tinta2);border-color:transparent}",
    ".gc-send{font:inherit;font-weight:600;font-size:14.5px;background:var(--senal);color:#fff;border:0;border-radius:10px;padding:0 16px;cursor:pointer}",
    ".gc-send:disabled{opacity:.5;cursor:not-allowed}",
    ".gc-acts{display:flex;align-items:center;gap:2px;flex:none}",
    ".gc-ico{background:transparent;border:0;color:#fff;cursor:pointer;width:36px;height:36px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;padding:0}",
    ".gc-ico:hover,.gc-ico[aria-pressed=true]{background:rgba(255,255,255,.16)}",
    ".gc-ico:focus-visible{outline:3px solid #fff;outline-offset:1px}",
    ".gc-ico svg{width:20px;height:20px}",
    ".gc-hist{flex:1;overflow-y:auto;padding:14px;background:var(--papel);display:none;flex-direction:column;gap:8px}",
    ".gc-hist.gc-show{display:flex}",
    ".gc-hist h3{margin:0 0 4px;font-size:14px;color:var(--tinta);font-weight:700}",
    ".gc-item{font:inherit;text-align:left;background:#fff;border:1px solid var(--linea);border-radius:10px;padding:10px 12px;cursor:pointer;color:var(--tinta)}",
    ".gc-item:hover{border-color:var(--tinta2)}",
    ".gc-item.gc-cur{border-color:var(--senal);box-shadow:inset 3px 0 0 var(--senal)}",
    ".gc-item b{display:block;font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".gc-item small{display:block;font-size:12px;color:var(--tinta2);margin-top:2px}",
    ".gc-new{font:inherit;font-weight:600;font-size:14px;background:var(--senal);color:#fff;border:0;border-radius:10px;padding:10px 12px;cursor:pointer}",
    ".gc-empty{font-size:13.5px;color:var(--tinta2)}",
    "@media (max-width:480px){.gc-panel{right:0;bottom:0;width:100vw;max-width:100vw;height:100vh;max-height:100vh;border-radius:0}}",
    "@media (prefers-reduced-motion:reduce){.gc-typing i{animation:none;opacity:.6}}"
  ].join("\n");

  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ---------- Conversaciones guardadas en este navegador ----------
   * Cada conversación tiene su propio session_id. El bot (en el servidor)
   * recuerda solo la conversación actual, así que una conversación nueva
   * empieza de cero. La lista de conversaciones se guarda en localStorage
   * y los mensajes se piden al servidor al reabrir una.
   */
  var K_LISTA = "bomar_chats", K_ACTUAL = "bomar_actual", MAX_CHATS = 20;

  function leer(k, def) {
    try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; }
  }
  function escribir(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {}
  }
  function nuevoId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "s" + Date.now() + Math.random().toString(36).slice(2, 12);
  }

  var chats = leer(K_LISTA, []);
  if (!Array.isArray(chats)) chats = [];
  var actual = leer(K_ACTUAL, null) || nuevoId();
  escribir(K_ACTUAL, actual);

  function buscarChat(id) {
    for (var i = 0; i < chats.length; i++) if (chats[i].id === id) return chats[i];
    return null;
  }
  function registrarChat(id, primerMensaje) {
    var c = buscarChat(id);
    if (c) { c.fecha = Date.now(); }
    else {
      chats.unshift({ id: id, titulo: primerMensaje.slice(0, 60), fecha: Date.now() });
      chats = chats.slice(0, MAX_CHATS);
    }
    chats.sort(function (a, b) { return b.fecha - a.fecha; });
    escribir(K_LISTA, chats);
  }

  /* ---------- Construcción del HTML ---------- */
  var ICO_NUEVO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6M9 14h6"/></svg>';
  var PALABRA_CLAVE = "NUEVA COTIZACIÓN";
  var ICO_HIST = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>';

  var root = document.createElement("div");
  root.className = "gc-root";
  root.innerHTML =
    '<button class="gc-fab" type="button" aria-label="Abrir chat con BOMAR">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>' +
      '<span>¿Te ayudamos?</span></button>' +
    '<section class="gc-panel" role="dialog" aria-label="Chat con el asistente de BOMAR">' +
      '<header class="gc-head"><div><div class="gc-title">Asistente de BOMAR</div>' +
      '<div class="gc-sub">Ingeniería, construcción y consultoría</div></div>' +
      '<div class="gc-acts">' +
        '<button class="gc-ico gc-btn-hist" type="button" aria-pressed="false" aria-label="Conversaciones anteriores" title="Conversaciones anteriores">' + ICO_HIST + '</button>' +
        '<button class="gc-ico gc-btn-new" type="button" aria-label="Nueva cotización" title="Nueva cotización">' + ICO_NUEVO + '</button>' +
        '<button class="gc-close" type="button" aria-label="Cerrar chat">&times;</button>' +
      '</div></header>' +
      '<div class="gc-msgs" aria-live="polite"></div>' +
      '<div class="gc-hist" aria-label="Conversaciones anteriores"></div>' +
      '<form class="gc-form" autocomplete="off">' +
        '<input class="gc-input" type="text" maxlength="1000" placeholder="Escribe tu mensaje" aria-label="Tu mensaje">' +
        '<button class="gc-send" type="submit">Enviar</button></form>' +
    '</section>';
  document.body.appendChild(root);

  var fab = root.querySelector(".gc-fab");
  var panel = root.querySelector(".gc-panel");
  var closeBtn = root.querySelector(".gc-close");
  var btnNuevo = root.querySelector(".gc-btn-new");
  var btnHist = root.querySelector(".gc-btn-hist");
  var msgs = root.querySelector(".gc-msgs");
  var hist = root.querySelector(".gc-hist");
  var form = root.querySelector(".gc-form");
  var input = root.querySelector(".gc-input");
  var sendBtn = root.querySelector(".gc-send");
  var chipsEl = null;
  var cargado = null;   // id de la conversación que está pintada en pantalla
  var busy = false;

  function scrollDown() { msgs.scrollTop = msgs.scrollHeight; }

  function addMsg(text, who) {
    var d = document.createElement("div");
    d.className = "gc-msg " + (who === "user" ? "gc-user" : "gc-bot");
    d.textContent = text;
    msgs.appendChild(d);
    scrollDown();
    return d;
  }

  function addNota(text) {
    var n = document.createElement("div");
    n.className = "gc-note";
    n.textContent = text;
    msgs.appendChild(n); scrollDown();
    return n;
  }

  function showTyping() {
    var t = document.createElement("div");
    t.className = "gc-msg gc-bot gc-typing";
    t.innerHTML = "<i></i><i></i><i></i>";
    t.setAttribute("aria-label", "El asistente está escribiendo");
    msgs.appendChild(t);
    scrollDown();
    return t;
  }

  function chipNueva() {
    var w = document.createElement("div");
    w.className = "gc-chips";
    var bt = document.createElement("button");
    bt.type = "button"; bt.className = "gc-chip"; bt.textContent = "+ Nueva cotización";
    bt.addEventListener("click", function () { w.remove(); nuevaCotizacion(); });
    w.appendChild(bt);
    msgs.appendChild(w); scrollDown();
  }

  function bienvenida() {
    msgs.innerHTML = "";
    addMsg("¡Hola! Soy el asistente virtual de BOMAR. Puedo explicarle nuestros servicios y prepararle una cotización. ¿En qué le podemos ayudar?", "bot");
    chipsEl = document.createElement("div");
    chipsEl.className = "gc-chips";
    ["Quiero una cotización", "¿Qué servicios ofrecen?", "Código de Red"].forEach(function (txt) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "gc-chip"; b.textContent = txt;
      b.addEventListener("click", function () { enviar(txt); });
      chipsEl.appendChild(b);
    });
    msgs.appendChild(chipsEl);
  }

  /* Pinta en pantalla la conversación `id` (pide sus mensajes al servidor si ya existía) */
  async function mostrarChat(id) {
    cargado = id;
    chipsEl = null;
    if (!buscarChat(id)) { bienvenida(); return; }
    msgs.innerHTML = "";
    var typing = showTyping();
    try {
      var res = await fetch(BACKEND + "/chat/" + encodeURIComponent(id) + "/historial");
      if (!res.ok) throw new Error("http " + res.status);
      var lista = await res.json();
      if (cargado !== id) return;  // el usuario cambió de conversación mientras cargaba
      typing.remove();
      if (!lista.length) {
        addNota("Esta conversación ya no está guardada en el servidor. Puedes seguir escribiendo aquí o empezar una nueva.");
        return;
      }
      lista.forEach(function (m) { addMsg(m.mensaje, m.remitente === "cliente" ? "user" : "bot"); });
    } catch (err) {
      if (cargado !== id) return;
      typing.remove();
      addNota("No pude cargar esta conversación. Revisa tu conexión e inténtalo de nuevo.");
      if (window.console) console.error(err);
    }
  }

  function verHistorial(mostrar) {
    btnHist.setAttribute("aria-pressed", mostrar ? "true" : "false");
    hist.classList.toggle("gc-show", mostrar);
    msgs.style.display = mostrar ? "none" : "";
    form.style.display = mostrar ? "none" : "";
    if (!mostrar) { input.focus(); return; }

    hist.innerHTML = "<h3>Tus conversaciones</h3>";
    var nueva = document.createElement("button");
    nueva.type = "button"; nueva.className = "gc-new"; nueva.textContent = "+ Nueva conversación";
    nueva.addEventListener("click", nuevaConversacion);
    hist.appendChild(nueva);

    if (!chats.length) {
      var v = document.createElement("p");
      v.className = "gc-empty";
      v.textContent = "Aquí aparecerán tus conversaciones anteriores.";
      hist.appendChild(v);
      return;
    }
    chats.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "gc-item" + (c.id === actual ? " gc-cur" : "");
      var t = document.createElement("b"); t.textContent = c.titulo || "Conversación";
      var f = document.createElement("small");
      f.textContent = new Date(c.fecha).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }) + (c.id === actual ? " · actual" : "");
      b.appendChild(t); b.appendChild(f);
      b.addEventListener("click", function () {
        actual = c.id; escribir(K_ACTUAL, actual);
        verHistorial(false);
        mostrarChat(actual);
      });
      hist.appendChild(b);
    });
  }

  /* Nueva cotización en el MISMO chat: el bot empieza de cero pero conserva al cliente */
  function nuevaCotizacion() {
    if (busy) return;
    verHistorial(false);
    if (!buscarChat(actual)) { mostrarChat(actual); return; }  // chat vacío: no hace falta
    enviar(PALABRA_CLAVE);
  }

  function nuevaConversacion() {
    if (busy) return;
    actual = nuevoId();
    escribir(K_ACTUAL, actual);
    verHistorial(false);
    mostrarChat(actual);
  }

  function open() {
    panel.classList.add("gc-open");
    fab.style.display = "none";
    if (cargado !== actual) mostrarChat(actual);
    setTimeout(function () { input.focus(); }, 50);
  }

  function close() {
    panel.classList.remove("gc-open");
    fab.style.display = "";
    fab.focus();
  }

  async function enviar(texto) {
    texto = (texto || "").trim();
    if (!texto || busy) return;
    busy = true; sendBtn.disabled = true; btnNuevo.disabled = true;
    if (chipsEl) { chipsEl.remove(); chipsEl = null; }
    var id = actual;
    registrarChat(id, texto);
    addMsg(texto, "user");
    input.value = "";

    var typing = showTyping();
    // Render gratis "duerme" al no usarse: la primera respuesta puede tardar.
    var nota = null;
    var timerNota = setTimeout(function () {
      nota = addNota("Estoy despertando el servidor, la primera respuesta puede tardar hasta un minuto.");
    }, 7000);

    var ctrl = new AbortController();
    var timeout = setTimeout(function () { ctrl.abort(); }, 90000);

    try {
      var res = await fetch(BACKEND + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: texto, session_id: id }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("http " + res.status);
      var data = await res.json();
      typing.remove();
      if (cargado === id) {
        addMsg(data.reply, "bot");
        if (/BOM-\d{4,}/.test(data.reply)) chipNueva();
      }
    } catch (err) {
      typing.remove();
      if (cargado === id) addMsg("No pude responder en este momento. Intenta de nuevo en unos minutos, o escríbenos a ventas@bomar.mx o llámanos al 818 086 0734.", "bot");
      if (window.console) console.error(err);
    } finally {
      clearTimeout(timerNota); clearTimeout(timeout);
      if (nota) nota.remove();
      busy = false; sendBtn.disabled = false; btnNuevo.disabled = false;
      input.focus();
    }
  }

  fab.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  btnNuevo.addEventListener("click", nuevaCotizacion);
  btnHist.addEventListener("click", function () {
    verHistorial(btnHist.getAttribute("aria-pressed") !== "true");
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); enviar(input.value); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.classList.contains("gc-open")) close();
  });

  // Para abrir el chat desde botones de la página: <button data-open-chat>
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("[data-open-chat]");
    if (el) { e.preventDefault(); open(); }
  });

  window.BomarChat = { open: open, close: close, nuevaCotizacion: nuevaCotizacion, nuevaConversacion: nuevaConversacion };
})();
