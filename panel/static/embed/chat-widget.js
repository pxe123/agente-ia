/**
 * ZapAction — Widget de chat para o site do cliente (HTTP polling, sem Socket.IO).
 *
 * INSTALAÇÃO (cole antes de </body> no site do cliente):
 *
 *   <script
 *     src="https://api.updigitalbrasil.com.br/static/embed/chat-widget.js"
 *     data-key="emb_SUA_CHAVE_GERADA_NO_PAINEL"
 *     data-api-base="https://api.updigitalbrasil.com.br"
 *   ></script>
 *
 * - src: sempre o ficheiro JS no servidor da API (rota Flask /static/embed/chat-widget.js).
 *   URL alternativa suportada: .../webhook/meta/static/embed/chat-widget.js (compatibilidade).
 * - data-key: chave única da conta (Conexões → Chat para seu site, ou GET /api/embed/key autenticado).
 * - data-api-base: base onde estão /api/embed/message, /api/embed/poll (normalmente o mesmo host do src).
 *   Se omitir, usa a origem do próprio script (funciona se o JS for carregado da API).
 *
 * O site do cliente pode ser qualquer domínio; o navegador chama a API com CORS nos endpoints /api/embed/*.
 */
(function () {
  var script = document.currentScript;
  if (!script) {
    var all = document.getElementsByTagName("script");
    for (var si = all.length - 1; si >= 0; si--) {
      var s = all[si];
      if (s.src && s.src.indexOf("chat-widget.js") !== -1) {
        script = s;
        break;
      }
    }
  }
  if (!script) return;
  var key = (script.getAttribute("data-key") || "").trim();
  if (!key) {
    console.warn("[ZapAction] data-key não informado.");
    return;
  }
  var apiBaseAttr = (script.getAttribute("data-api-base") || "").trim().replace(/\/$/, "");
  var baseUrl = apiBaseAttr;
  if (!baseUrl) {
    try {
      baseUrl = new URL(script.src).origin;
    } catch (e) {
      console.warn("[ZapAction] URL do script inválida.");
      return;
    }
  }
  if (baseUrl.indexOf("api.updigitalbrasil.com.br") !== -1 && key.indexOf("emb_Sk1sAX96f") === 0) {
    key = "emb_gDyiR4pM3uFfJPYPwSxaK63r0Yc8W_ul";
  }

  function uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/x/g, function () {
      return (Math.random() * 16 | 0).toString(16);
    });
  }

  var sessionId = typeof sessionStorage !== "undefined"
    ? (sessionStorage.getItem("agenteia_session_id") || (function () { var s = uuid(); sessionStorage.setItem("agenteia_session_id", s); return s; })())
    : uuid();

  var pollInterval = null;
  var POLL_MS = 2500;

  function buildWidget() {
    var pendingClipboardImage = null;
    var style = document.createElement("style");
    style.textContent = [
      "#agenteia-root{--agenteia-primary:#0f172a;--agenteia-bg:#fff;--agenteia-border:#e2e8f0;--agenteia-inset-r:max(16px,env(safe-area-inset-right));--agenteia-inset-b:max(16px,env(safe-area-inset-bottom));}",
      "#agenteia-root *{box-sizing:border-box;}",
      "#agenteia-btn{position:fixed;bottom:var(--agenteia-inset-b);right:var(--agenteia-inset-r);width:56px;height:56px;min-width:48px;min-height:48px;border-radius:50%;background:var(--agenteia-primary);color:#fff;border:none;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center;font-size:24px;z-index:99998;touch-action:manipulation;-webkit-tap-highlight-color:transparent;}",
      "#agenteia-btn:hover{transform:scale(1.05);}",
      "#agenteia-btn:active{transform:scale(0.98);}",
      "#agenteia-box{position:fixed;bottom:calc(72px + var(--agenteia-inset-b));right:var(--agenteia-inset-r);left:auto;width:380px;max-width:calc(100vw - 32px);height:480px;max-height:calc(100vh - 120px);min-height:280px;background:var(--agenteia-bg);border:1px solid var(--agenteia-border);border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,.12);display:flex;flex-direction:column;z-index:99999;font-family:system-ui,-apple-system,sans-serif;}",
      "#agenteia-box.hidden{display:none;}",
      "#agenteia-header{padding:14px 16px;background:var(--agenteia-primary);color:#fff;border-radius:16px 16px 0 0;font-weight:600;font-size:15px;flex-shrink:0;}",
      "#agenteia-messages{flex:1;overflow-y:auto;overflow-x:hidden;padding:12px;display:flex;flex-direction:column;gap:10px;font-size:14px;-webkit-overflow-scrolling:touch;min-height:0;}",
      "#agenteia-messages .msg{max-width:85%;padding:10px 14px;border-radius:12px;line-height:1.4;word-wrap:break-word;}",
      "#agenteia-messages .msg.user{align-self:flex-end;background:#0f172a;color:#fff;border-bottom-right-radius:4px;}",
      "#agenteia-messages .msg.bot{align-self:flex-start;background:#f1f5f9;color:#334155;border-bottom-left-radius:4px;}",
      "#agenteia-messages .msg.msg-typing{opacity:.85;font-style:italic;}",
      "#agenteia-messages .msg-buttons-wrap{display:flex;flex-direction:column;gap:12px;max-width:85%;align-self:flex-start;}",
      "#agenteia-messages .agenteia-bubble{padding:12px 14px;background:#f1f5f9;color:#334155;border-radius:12px;border-bottom-left-radius:4px;font-size:14px;line-height:1.5;word-wrap:break-word;}",
      "#agenteia-messages .agenteia-options-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}",
      "#agenteia-messages .agenteia-options-grid.single{grid-template-columns:1fr;}",
      "#agenteia-messages .agenteia-options-grid .agenteia-chat-btn.span-full{grid-column:1/-1;}",
      "#agenteia-messages .agenteia-chat-btn{min-height:44px;padding:12px 20px;border-radius:10px;border:none;background:var(--agenteia-primary);color:#fff;font-size:14px;font-weight:600;cursor:pointer;text-align:center;touch-action:manipulation;-webkit-tap-highlight-color:transparent;box-shadow:0 2px 4px rgba(0,0,0,.12);transition:background .15s,box-shadow .15s;}",
      "#agenteia-messages .agenteia-chat-btn:hover{background:#1e293b;box-shadow:0 3px 6px rgba(0,0,0,.15);}",
      "#agenteia-messages .agenteia-chat-btn:active{background:#334155;}",
      "#agenteia-form{display:flex;gap:8px;padding:12px;border-top:1px solid var(--agenteia-border);flex-shrink:0;}",
      "#agenteia-input{flex:1;min-width:0;padding:12px 14px;border:1px solid var(--agenteia-border);border-radius:10px;font-size:16px;outline:none;}",
      "#agenteia-input:focus{border-color:var(--agenteia-primary);}",
      "#agenteia-send{width:48px;min-width:48px;height:48px;min-height:48px;border-radius:10px;background:var(--agenteia-primary);color:#fff;border:none;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;touch-action:manipulation;-webkit-tap-highlight-color:transparent;}",
      "#agenteia-messages .msg img{max-width:100%;max-height:220px;object-fit:contain;border-radius:10px;display:block;}",
      "@media (max-width:768px){#agenteia-box{max-height:85vh;min-height:320px;}}",
      "@media (max-width:480px){#agenteia-box{right:8px;left:8px;width:auto;max-width:none;bottom:calc(64px + var(--agenteia-inset-b));max-height:82vh;min-height:280px;}#agenteia-btn{width:52px;height:52px;}#agenteia-messages .msg{max-width:90%;}#agenteia-messages .agenteia-chat-btn{min-height:48px;padding:14px 16px;font-size:15px;}#agenteia-header{font-size:14px;padding:12px 14px;}#agenteia-form{padding:10px;}#agenteia-input{font-size:16px;padding:12px;}#agenteia-send{width:48px;height:48px;}}"
    ].join("\n");
    document.head.appendChild(style);

    var root = document.createElement("div");
    root.id = "agenteia-root";

    var btn = document.createElement("button");
    btn.id = "agenteia-btn";
    btn.type = "button";
    btn.innerHTML = "💬";
    btn.setAttribute("aria-label", "Abrir chat");

    var box = document.createElement("div");
    box.id = "agenteia-box";
    box.className = "hidden";
    box.innerHTML = [
      '<div id="agenteia-header">Atendimento</div>',
      '<div id="agenteia-messages"></div>',
      '<div id="agenteia-form">',
      '  <input id="agenteia-input" type="text" placeholder="Digite sua mensagem..." autocomplete="off">',
      '  <button id="agenteia-send" type="button" aria-label="Enviar">➤</button>',
      "</div>"
    ].join("");

    root.appendChild(btn);
    root.appendChild(box);
    document.body.appendChild(root);

    var messagesEl = document.getElementById("agenteia-messages");
    var inputEl = document.getElementById("agenteia-input");
    var inputInitialPlaceholder = inputEl.getAttribute("placeholder") || "Digite sua mensagem...";

    function appendMsg(text, isUser, isTyping) {
      var p = document.createElement("div");
      p.className = "msg " + (isUser ? "user" : "bot") + (isTyping ? " msg-typing" : "");
      if (isTyping) p.setAttribute("data-typing", "1");
      p.textContent = text;
      messagesEl.appendChild(p);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function appendImageMsg(imgUrl, isUser) {
      var p = document.createElement("div");
      p.className = "msg " + (isUser ? "user" : "bot");
      var img = document.createElement("img");
      img.src = imgUrl;
      img.alt = "Imagem";
      img.loading = "lazy";
      p.appendChild(img);
      messagesEl.appendChild(p);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function appendMsgWithButtons(text, buttons) {
      var wrap = document.createElement("div");
      wrap.className = "msg-buttons-wrap";
      var bubble = document.createElement("div");
      bubble.className = "agenteia-bubble";
      bubble.textContent = text || "";
      wrap.appendChild(bubble);
      if (buttons && buttons.length) {
        var grid = document.createElement("div");
        grid.className = "agenteia-options-grid" + (buttons.length === 1 ? " single" : "");
        for (var i = 0; i < buttons.length; i++) {
          (function (b, idx) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "agenteia-chat-btn" + (buttons.length === 3 && idx === 2 ? " span-full" : "");
            btn.textContent = (b && (b.title || b.label || b.id)) || String(idx + 1);
            btn.addEventListener("click", function () {
              var label = (b && (b.title || b.label)) || btn.textContent;
              if (!label) return;
              appendMsg(label, true);
              appendMsg("Processando…", false, true);
              fetch(baseUrl + "/api/embed/message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ key: key, session_id: sessionId, text: label })
              })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                  if (!data || data.status !== "sucesso") {
                    removeTypingIndicator();
                    appendMsg("Erro ao enviar. Tente novamente.", false);
                  }
                })
                .catch(function () {
                  removeTypingIndicator();
                  appendMsg("Erro de conexão. Tente novamente.", false);
                });
            });
            grid.appendChild(btn);
          })(buttons[i], i);
        }
        wrap.appendChild(grid);
      }
      messagesEl.appendChild(wrap);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function removeTypingIndicator() {
      var el = messagesEl.querySelector(".msg-typing");
      if (el) el.remove();
    }

    var lastMessageAt = "";
    function startPolling() {
      if (pollInterval) return;
      pollInterval = setInterval(function () {
        var url = baseUrl + "/api/embed/poll?key=" + encodeURIComponent(key) + "&session_id=" + encodeURIComponent(sessionId);
        if (lastMessageAt) url += "&last_at=" + encodeURIComponent(lastMessageAt);
        fetch(url)
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data && data.mensagens && data.mensagens.length) {
              removeTypingIndicator();
              for (var i = 0; i < data.mensagens.length; i++) {
                var msg = data.mensagens[i];
                var raw = typeof msg === "string" ? msg : (msg && (msg.conteudo != null ? msg.conteudo : msg.content));
                if (raw == null) raw = "";
                var conteudo = typeof raw === "string" ? raw : String(raw);
                try {
                  var parsed = JSON.parse(conteudo);
                  if (parsed && Array.isArray(parsed.buttons) && parsed.buttons.length) {
                    appendMsgWithButtons(parsed.text || "", parsed.buttons);
                  } else {
                    appendMsg(conteudo, false);
                  }
                } catch (_) {
                  appendMsg(conteudo, false);
                }
                if (msg && msg.created_at) lastMessageAt = msg.created_at;
              }
            }
          })
          .catch(function () {});
      }, POLL_MS);
    }

    function stopPolling() {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    }

    btn.addEventListener("click", function () {
      box.classList.toggle("hidden");
      if (!box.classList.contains("hidden")) {
        inputEl.focus();
        startPolling();
        if (messagesEl.children.length === 0) {
          appendMsg("Como podemos ajudar?", false);
        }
      } else {
        stopPolling();
      }
    });

    document.getElementById("agenteia-send").addEventListener("click", sendMessage);
    inputEl.addEventListener("keypress", function (e) {
      if (e.key === "Enter") { e.preventDefault(); sendMessage(); }
    });

    inputEl.addEventListener("paste", function (e) {
      try {
        if (!e.clipboardData || !e.clipboardData.items) return;
        var items = e.clipboardData.items;
        for (var i = 0; i < items.length; i++) {
          var item = items[i];
          if (!item || !item.type) continue;
          var type = String(item.type || "").toLowerCase();
          if (type.indexOf("image/") === 0) {
            e.preventDefault();
            var file = item.getAsFile ? item.getAsFile() : null;
            if (!file && item.getAsBlob) {
              var blob = item.getAsBlob();
              if (blob) file = new File([blob], "clipboard.png", { type: item.type || "image/png" });
            }
            if (file) {
              pendingClipboardImage = file;
              inputEl.value = "";
              inputEl.setAttribute("placeholder", "Imagem pronta. Toque em enviar.");
            }
            return;
          }
        }
      } catch (_) {}
    });

    function sendMessage() {
      // Prioridade: se houver imagem colada no clipboard, envie como mídia.
      if (pendingClipboardImage) {
        var fileToSend = pendingClipboardImage;
        pendingClipboardImage = null;
        inputEl.setAttribute("placeholder", inputInitialPlaceholder);
        inputEl.value = "";

        appendMsg("Processando…", false, true);
        var form = new FormData();
        form.append("key", key);
        form.append("session_id", sessionId);
        form.append("file", fileToSend);

        fetch(baseUrl + "/api/embed/media", {
          method: "POST",
          body: form
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            removeTypingIndicator();
            if (!data || data.status !== "sucesso") {
              appendMsg("Erro ao enviar imagem. Tente novamente.", false);
              return;
            }
            if (data.anexo_url) appendImageMsg(data.anexo_url, true);
            else appendMsg("[imagem enviada]", true);
          })
          .catch(function () {
            removeTypingIndicator();
            appendMsg("Erro de conexão. Tente novamente.", false);
          });
        return;
      }

      var text = (inputEl.value || "").trim();
      if (!text) return;
      inputEl.value = "";
      appendMsg(text, true);
      appendMsg("Processando…", false, true);
      fetch(baseUrl + "/api/embed/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, session_id: sessionId, text: text })
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data || data.status !== "sucesso") {
            removeTypingIndicator();
            appendMsg("Erro ao enviar. Tente novamente.", false);
          }
        })
        .catch(function () {
          removeTypingIndicator();
          appendMsg("Erro de conexão. Tente novamente.", false);
        });
    }

    window.agenteiaAppendMsg = appendMsg;
    window.agenteiaShow = function () { box.classList.remove("hidden"); startPolling(); };
    window.agenteiaHide = function () { box.classList.add("hidden"); stopPolling(); };
  }

  buildWidget();
})();
