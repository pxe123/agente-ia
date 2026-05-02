// Reutiliza o socket do layout (notificação em todas as páginas) ou cria um; só polling evita falha de upgrade atrás do Caddy
// WebSocket primeiro reduz POSTs de polling (menos 400 em dev/Windows); polling fica como fallback.
const _AGENTEIA_SOCKET_OPTS = {
    transports: ["polling"],
    upgrade: false,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
};
const socket = window.appSocket || io(_AGENTEIA_SOCKET_OPTS);
if (!window.appSocket) window.appSocket = socket;
let mensagensGlobais = [];
let idRemotoAtivo = null;
let canalAtivo = typeof PRIMEIRO_CANAL !== "undefined" ? PRIMEIRO_CANAL : "whatsapp";
/** Quando a API de mensagens falha, guardamos o erro para exibir na lista e tirar o loading. */
let erroCarregamentoChat = null;
/** Último canal que carregamos (evita som/notificação ao trocar de aba WhatsApp/Messenger). */
let ultimoCanalCarregado = null;
/** Nome e foto dos chats WhatsApp (GET /api/waha/chats/overview). id -> { name, picture }. */
let wahaChatsOverview = {};
/** Carregamento de mensagens antigas ao rolar para cima. */
let loadingMaisAntigas = false;
/** Referência única ao handler de scroll (evita listeners duplicados ao trocar de conversa). */
let chatScrollHandler = null;
/** remote_id normalizado -> true quando não há mais mensagens antigas. */
let semMaisAntigasPorRemote = {};
/** Gravação de áudio: estado e chunks para enviar. */
let gravandoAudio = false;
let mediaRecorderAudio = null;
let chunksAudio = [];
/** Clipboard (Ctrl+V): imagem pronta para enviar como anexo (sem enviar automaticamente). */
let pendingClipboardFile = null;
let inputMsgPlaceholderOriginal = "";
const INPUT_MSG_MAX_HEIGHT = 150;
let termoBuscaContato = "";

/** Estado da conversa no backend: "atendimento_ia" ou "atendimento_humano" (fonte do indicador IA). */
let currentSetorEstado = "atendimento_ia";

// Não lidas por canal e por remote_id (só mensagens de "user")
const unreadByChannel = { whatsapp: {}, facebook: {}, instagram: {}, website: {} };

const CANAL_LABELS = { whatsapp: "WhatsApp", facebook: "Messenger", instagram: "Instagram", website: "Site" };

/**
 * Converte texto em nós com links clicáveis (sem usar innerHTML).
 * - Mantém o texto seguro (evita XSS)
 * - Linkifica http(s):// e www.*
 */
function appendLinkifiedText(parentEl, rawText, linkClass) {
    if (!parentEl) return;
    const text = String(rawText || "");
    // Limpa conteúdo anterior
    while (parentEl.firstChild) parentEl.removeChild(parentEl.firstChild);
    if (!text) return;

    const urlRe = /((https?:\/\/|www\.)[^\s<]+)/gi;
    let lastIndex = 0;
    let match;
    while ((match = urlRe.exec(text)) !== null) {
        const start = match.index;
        const end = urlRe.lastIndex;
        if (start > lastIndex) {
            parentEl.appendChild(document.createTextNode(text.slice(lastIndex, start)));
        }
        let urlText = text.slice(start, end);

        // Remove pontuação final comum que não faz parte do link
        const mPunct = urlText.match(/[)\].,!?;:]+$/);
        let trailing = "";
        if (mPunct) {
            trailing = mPunct[0];
            urlText = urlText.slice(0, -trailing.length);
        }

        const href = urlText.toLowerCase().startsWith("http") ? urlText : "https://" + urlText;
        const a = document.createElement("a");
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = linkClass || "text-blue-600 hover:text-blue-700";
        a.textContent = urlText;
        parentEl.appendChild(a);
        if (trailing) parentEl.appendChild(document.createTextNode(trailing));
        lastIndex = end;
    }
    if (lastIndex < text.length) {
        parentEl.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
}

/**
 * Aviso visível no painel (não depende só de alert(), que alguns browsers ou modos bloqueiam).
 * kind: "error" | "warn"
 */
function showPainelToast(text, kind) {
    const k = kind === "warn" ? "warn" : "error";
    let host = document.getElementById("painel-toast-host");
    if (!host) {
        host = document.createElement("div");
        host.id = "painel-toast-host";
        host.setAttribute("aria-live", "polite");
        host.className =
            "fixed top-16 sm:top-20 left-1/2 -translate-x-1/2 z-[100] max-w-md w-[calc(100%-2rem)] flex flex-col gap-2 pointer-events-none items-stretch";
        document.body.appendChild(host);
    }
    const el = document.createElement("div");
    el.className =
        "pointer-events-auto px-4 py-3 rounded-lg text-sm shadow-lg border leading-snug " +
        (k === "warn"
            ? "bg-amber-50 border-amber-300 text-amber-950"
            : "bg-red-50 border-red-300 text-red-950");
    el.setAttribute("role", "alert");
    el.textContent = text;
    host.appendChild(el);
    setTimeout(() => {
        el.remove();
        if (!host.children.length) {
            host.remove();
        }
    }, 14000);
}

/** Normaliza remote_id para comparação (ex.: 5511999999999 e 5511999999999@s.whatsapp.net viram iguais). */
function normalizarRemoteId(rid) {
    return String(rid || "").replace(/@.*$/, "").trim();
}

/**
 * Chave alinhada ao backend (`_remote_id_chave_painel_whatsapp`) para badges não lidos / marcar-lido.
 * Sem isto, API devolve 5514… mas o clique limpa outra chave e o contador do separador WhatsApp volta.
 */
function chaveUnreadRemoto(canal, remote_id) {
    const c = String(canal || "").toLowerCase();
    const base = normalizarRemoteId(remote_id);
    if (!base) return "";
    if (c !== "whatsapp") return base;
    const d = base.replace(/\D/g, "");
    if (!d) return base;
    if (d.length === 10 || d.length === 11) return "55" + d;
    if ((d.length === 12 || d.length === 13) && d.startsWith("55")) return d;
    return base;
}

/** Mesmo interlocutor no canal (WhatsApp: compara chave E.164; evita marcar não-lido com a conversa aberta). */
function mesmoContatoNoCanal(canal, a, b) {
    const c = String(canal || "").toLowerCase();
    if (a == null || b == null) return false;
    if (c === "whatsapp") {
        const ka = chaveUnreadRemoto("whatsapp", a);
        const kb = chaveUnreadRemoto("whatsapp", b);
        return Boolean(ka && kb && ka === kb);
    }
    return normalizarRemoteId(a) === normalizarRemoteId(b);
}

/** Usado em layout.html para não mostrar notificação global da conversa que está aberta no /chat. */
window.agenteiaChatAberto = function (canal, remote_id) {
    if (!idRemotoAtivo || !canalAtivo) return false;
    if (String(canal || "whatsapp").toLowerCase() !== String(canalAtivo).toLowerCase()) return false;
    return mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo);
};

const LIMITE_HISTORICO_INICIAL = 100;
const LIMITE_PAGINA_ANTIGA = 50;

/** Ordem estável: cronologia + desempate por `id` (alinhado à paginação do servidor). */
function compararMensagemHistorico(a, b) {
    const ta = new Date(a.created_at || 0) - new Date(b.created_at || 0);
    if (ta !== 0) return ta;
    return String(a.id || "").localeCompare(String(b.id || ""));
}

function normalizarTextoBusca(texto) {
    return String(texto || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .trim();
}

/** Auto-resize suave do textarea de mensagem (cresce até o limite e depois habilita scroll interno). */
function autoResizeInputMsg(inputEl) {
    if (!inputEl) return;
    const maxHeight = INPUT_MSG_MAX_HEIGHT;
    inputEl.style.height = "auto";
    const nextHeight = Math.min(inputEl.scrollHeight, maxHeight);
    inputEl.style.height = `${nextHeight}px`;
    inputEl.style.overflowY = inputEl.scrollHeight > maxHeight ? "auto" : "hidden";
}

/** Evita "Unexpected token '<'" quando a sessão expira e o servidor devolve HTML (página de login). */
async function fetchJson(url, options) {
    const res = await fetch(url, options);
    const text = await res.text();
    if (typeof text === "string" && text.trim().startsWith("<")) {
        window.location.href = "/?sessao=expirada";
        return null;
    }
    try {
        return JSON.parse(text);
    } catch (e) {
        if (res.status === 401) window.location.href = "/?sessao=expirada";
        throw e;
    }
}

const FUSO_BR = "America/Sao_Paulo";

/** Data e hora no fuso do Brasil. Lista: hoje = "HH:mm", ontem = "Ontem HH:mm", outro = "dd/MM/yy HH:mm". */
function formatHora(iso) {
    if (!iso) return "";
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        const optsH = { hour: "2-digit", minute: "2-digit", timeZone: FUSO_BR };
        const optsD = { day: "2-digit", month: "2-digit", year: "2-digit", timeZone: FUSO_BR };
        const dStr = d.toLocaleDateString("pt-BR", optsD);
        const hojeStr = new Date().toLocaleDateString("pt-BR", optsD);
        if (dStr === hojeStr) return d.toLocaleTimeString("pt-BR", optsH);
        const ontem = new Date();
        ontem.setDate(ontem.getDate() - 1);
        const ontemStr = ontem.toLocaleDateString("pt-BR", optsD);
        if (dStr === ontemStr) return "Ontem " + d.toLocaleTimeString("pt-BR", optsH);
        return dStr + " " + d.toLocaleTimeString("pt-BR", optsH);
    } catch (e) {
        return "";
    }
}

/** Data e hora completas no fuso do Brasil (ex.: 07/03/2025 14:30). */
function formatDataHoraBR(iso) {
    if (!iso) return "";
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleString("pt-BR", {
            day: "2-digit",
            month: "2-digit",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            timeZone: FUSO_BR
        });
    } catch (e) {
        return "";
    }
}

function isSomNotificacaoAtivo() {
    const el = document.getElementById("som-notificacao");
    if (el) return el.checked;
    return localStorage.getItem("agenteia_som") !== "0";
}

function setSomNotificacao(ativo) {
    localStorage.setItem("agenteia_som", ativo ? "1" : "0");
    const el = document.getElementById("som-notificacao");
    if (el) el.checked = ativo;
}

let _audioContext = null;
let _audioContextUnlocked = false;

function unlockAudioContext() {
    if (_audioContextUnlocked) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    if (!_audioContext) _audioContext = new Ctx();
    if (_audioContext.state === "suspended") {
        _audioContext.resume().then(() => { _audioContextUnlocked = true; }).catch(() => {});
    } else {
        _audioContextUnlocked = true;
    }
}

function tocarSomNotificacao() {
    if (!isSomNotificacaoAtivo()) return;
    try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        if (!_audioContext) _audioContext = new Ctx();
        if (_audioContext.state === "suspended") {
            _audioContext.resume().catch(() => {});
        }
        const osc = _audioContext.createOscillator();
        const gain = _audioContext.createGain();
        osc.connect(gain);
        gain.connect(_audioContext.destination);
        osc.frequency.value = 800;
        osc.type = "sine";
        gain.gain.setValueAtTime(0.15, _audioContext.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, _audioContext.currentTime + 0.15);
        osc.start(_audioContext.currentTime);
        osc.stop(_audioContext.currentTime + 0.15);
    } catch (e) {
        console.warn("Som de notificação não disponível:", e);
    }
}

function mostrarNotificacaoDesktop(titulo, corpo) {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
        try { new Notification(titulo, { body: corpo || "Nova mensagem", icon: "/static/images/logo.png" }); } catch (e) {}
    } else if (Notification.permission !== "denied") {
        Notification.requestPermission().then((p) => { if (p === "granted") mostrarNotificacaoDesktop(titulo, corpo); });
    }
}

function getContactInfo(contato) {
    const canal = contato.canal || "whatsapp";
    const rid = contato.remote_id || "";
    if (canal === "website") {
        const short = rid.length > 8 ? rid.slice(0, 8) + "…" : rid;
        return { nome: "Visitante " + (short || "site"), foto: "https://ui-avatars.com/api/?name=Visitante&background=64748b&color=fff" };
    }
    if (canal === "instagram") {
        return { nome: contato.push_name || "Instagram", foto: contato.profile_pic || "https://ui-avatars.com/api/?name=IG&background=e4405f&color=fff" };
    }
    if (canal === "facebook") {
        return { nome: contato.push_name || "Messenger", foto: contato.profile_pic || "https://ui-avatars.com/api/?name=FB&background=0084ff&color=fff" };
    }
    const overview = wahaChatsOverview[rid] || (!rid.includes("@") ? (wahaChatsOverview[rid + "@c.us"] || wahaChatsOverview[rid + "@lid"]) : null);
    const nome = (overview && overview.name) || contato.push_name || rid.split("@")[0] || rid;
    const foto = (overview && overview.picture) || contato.profile_pic || `https://ui-avatars.com/api/?name=${encodeURIComponent(String(rid).replace(/@.*$/, ""))}&background=random`;
    return { nome, foto };
}

function updateIndicadorIA() {
    const indicador = document.getElementById("indicador-ia");
    if (!indicador) return;
    const iaAtendendo = currentSetorEstado === "atendimento_ia";
    indicador.classList.toggle("hidden", !iaAtendendo);
    indicador.classList.toggle("flex", iaAtendendo);
    indicador.setAttribute("aria-hidden", iaAtendendo ? "false" : "true");
}

function contagemUnreadCanal(canal) {
    return Object.keys(unreadByChannel[canal] || {}).filter((k) => unreadByChannel[canal][k]).length;
}

function atualizarBadgesCanais() {
    ["whatsapp", "facebook", "instagram", "website"].forEach((c) => {
        const el = document.getElementById("badge-" + (c === "facebook" ? "facebook" : c === "website" ? "website" : c));
        if (!el) return;
        const n = contagemUnreadCanal(c);
        if (n > 0) {
            el.textContent = n > 99 ? "99+" : String(n);
            el.classList.remove("hidden");
            el.style.display = "";
        } else {
            el.textContent = "";
            el.classList.add("hidden");
            el.style.display = "none";
        }
    });
    const btnMarcarTodas = document.getElementById("btn-marcar-todas-lidas");
    if (btnMarcarTodas) btnMarcarTodas.classList.toggle("hidden", contagemUnreadCanal(canalAtivo) === 0);
}

function marcarUnread(canal, remote_id) {
    if (!unreadByChannel[canal]) unreadByChannel[canal] = {};
    unreadByChannel[canal][chaveUnreadRemoto(canal, remote_id)] = true;
    atualizarBadgesCanais();
}

function limparUnread(canal, remote_id) {
    const key = chaveUnreadRemoto(canal, remote_id);
    if (unreadByChannel[canal]) delete unreadByChannel[canal][key];
    atualizarBadgesCanais();
}

/** Marca todas as conversas do canal atual como lidas (limpa notificações fantasmas de chats que sumiram da lista). */
async function marcarTodasComoLidas() {
    const canal = canalAtivo;
    try {
        const res = await fetch("/api/mensagens/contatos-nao-lidos");
        if (!res.ok) return;
        const data = await res.json().catch(() => ({}));
        const ids = data[canal];
        if (!Array.isArray(ids) || ids.length === 0) {
            if (unreadByChannel[canal]) Object.keys(unreadByChannel[canal]).forEach((k) => delete unreadByChannel[canal][k]);
            atualizarBadgesCanais();
            renderizarListaContatos();
            return;
        }
        ids.forEach((rid) => marcarLidoNoServidor(canal, rid, { immediate: true }));
        if (unreadByChannel[canal]) unreadByChannel[canal] = {};
        atualizarBadgesCanais();
        renderizarListaContatos();
    } catch (e) {
        console.warn("[Chat] Erro ao marcar todas como lidas:", e);
    }
}

function limparUnreadCanalAoAbrir(remote_id) {
    limparUnread(canalAtivo, remote_id);
}

/** Debounce por canal+remote_id: evita rajadas de POST ao receber várias mensagens seguidas. */
const _marcarLidoTimers = {};
function marcarLidoNoServidor(canal, remote_id, opts) {
    const rid = chaveUnreadRemoto(canal, remote_id);
    if (!canal || !rid) return;
    const key = canal + "|" + rid;
    const immediate = opts && opts.immediate === true;

    function doPost(fetchOpts) {
        return fetch("/api/mensagens/marcar-lido", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: JSON.stringify({ canal, remote_id: rid }),
            ...(fetchOpts || {})
        })
            .then(() => atualizarBadgesCanais())
            .catch(() => {});
    }

    if (immediate) {
        if (_marcarLidoTimers[key]) {
            clearTimeout(_marcarLidoTimers[key]);
            delete _marcarLidoTimers[key];
        }
        return doPost();
    }

    if (_marcarLidoTimers[key]) clearTimeout(_marcarLidoTimers[key]);
    _marcarLidoTimers[key] = setTimeout(() => {
        delete _marcarLidoTimers[key];
        doPost();
    }, 500);
}

/** Distância em px do fundo para considerar "no final" (evita puxar scroll se o usuário está lendo histórico). */
const CHAT_SCROLL_BOTTOM_MARGIN_PX = 64;

/**
 * True se o usuário está visualmente no fim da lista (pode receber auto-scroll em novas mensagens).
 */
function estaPertoDoFundo(container, margemPx) {
    if (!container) return true;
    const m = typeof margemPx === "number" ? margemPx : CHAT_SCROLL_BOTTOM_MARGIN_PX;
    const gap = container.scrollHeight - container.scrollTop - container.clientHeight;
    return gap <= m;
}

/**
 * Aplica scroll ao fundo após layout/pintura (scrollHeight atualizado).
 */
function rolarFinal(instant) {
    const run = () => {
        const container = document.getElementById("chat-container");
        if (!container) return;
        const top = container.scrollHeight;
        if (instant) {
            const antes = container.style.scrollBehavior;
            container.style.scrollBehavior = "auto";
            container.scrollTop = top;
            container.style.scrollBehavior = antes || "";
        } else {
            container.scrollTo({ top, behavior: "smooth" });
        }
    };
    requestAnimationFrame(() => {
        requestAnimationFrame(run);
    });
}

/** Só rola ao fundo se, antes de alterar o DOM, o usuário já estava no fim (ex.: nova mensagem via socket/polling). */
function rolarFinalSeEstavaNoFundo(container, estavaNoFundo) {
    if (!estavaNoFundo) return;
    rolarFinal(true);
}

socket.on("nova_mensagem", (data) => {
    if (data.cliente_id != null && String(data.cliente_id) !== String(MEU_ID)) return;
    const canal = data.canal || "whatsapp";
    const isUser = data.funcao === "user";
    if (!data.created_at) data.created_at = new Date().toISOString();

    if (existeDuplicataRecente(mensagensGlobais, data, 25000)) return;

    if (canal !== canalAtivo) {
        if (isUser) {
            marcarUnread(canal, data.remote_id);
            tocarSomNotificacao();
            if (document.hidden) mostrarNotificacaoDesktop("Nova mensagem", (data.conteudo || "").slice(0, 60) + (data.conteudo && data.conteudo.length > 60 ? "…" : ""));
        } else {
            atualizarBadgesCanais();
        }
        return;
    }

    // Evitar duplicata: se for resposta nossa que já mostramos ao enviar, não adicionar de novo
    const ehConversaAbertaAgora = Boolean(idRemotoAtivo && mesmoContatoNoCanal(canal, data.remote_id, idRemotoAtivo));
    if (!isUser) {
        const ultima = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canal, m.remote_id, data.remote_id)).pop();
        if (ultima && ultima.funcao === "assistant" && ultima.conteudo === data.conteudo) return;
    } else {
        // Só marcar não lida e notificar se NÃO for a conversa que está aberta na tela
        if (!ehConversaAbertaAgora) {
            marcarUnread(canal, data.remote_id);
            tocarSomNotificacao();
            if (document.hidden) mostrarNotificacaoDesktop("Nova mensagem", (data.conteudo || "").slice(0, 60) + (data.conteudo && data.conteudo.length > 60 ? "…" : ""));
        } else if (!document.hidden) {
            marcarLidoNoServidor(canal, data.remote_id);
        }
    }

    mensagensGlobais.push(data);
    if (idRemotoAtivo && mesmoContatoNoCanal(canal, data.remote_id, idRemotoAtivo)) {
        const container = document.getElementById("chat-container");
        const estavaNoFundo = container ? estaPertoDoFundo(container) : true;
        adicionarBalaoChat(data, false, false);
        rolarFinalSeEstavaNoFundo(container, estavaNoFundo);
    }
    renderizarListaContatos();
});

document.addEventListener("visibilitychange", () => {
    if (!document.hidden && idRemotoAtivo) {
        marcarLidoNoServidor(canalAtivo, idRemotoAtivo, { immediate: true });
    }
});

/** Antes de fechar/atualizar a aba, envia leitura pendente (debounce de 500ms pode não ter disparado). */
window.addEventListener("pagehide", () => {
    if (!idRemotoAtivo) return;
    const rid = chaveUnreadRemoto(canalAtivo, idRemotoAtivo);
    if (!rid || !canalAtivo) return;
    const key = canalAtivo + "|" + rid;
    if (_marcarLidoTimers[key]) {
        clearTimeout(_marcarLidoTimers[key]);
        delete _marcarLidoTimers[key];
    }
    try {
        fetch("/api/mensagens/marcar-lido", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: JSON.stringify({ canal: canalAtivo, remote_id: rid }),
            keepalive: true
        }).catch(() => {});
    } catch (_) {}
});

// Atualiza a área do chat aberto. Se só chegou mensagem nova, só acrescenta o balão e rola (sem redesenhar tudo).
function atualizarAreaChatAberta(sempreAtualizar) {
    if (!idRemotoAtivo) return;
    const container = document.getElementById("chat-container");
    if (!container) return;
    const mensagensFiltradas = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, idRemotoAtivo));
    const numBaloes = container.querySelectorAll(".msg-balao").length;

    if (!sempreAtualizar && numBaloes === mensagensFiltradas.length) return;

    // Temos mais balões que o servidor (mensagem otimista ao enviar): não redesenhar para não piscar
    if (numBaloes > mensagensFiltradas.length && numBaloes > 0) return;

    // Se só aumentou o número de mensagens, só acrescenta as novas (evita a tela "mexer")
    if (mensagensFiltradas.length > numBaloes && numBaloes > 0) {
        const chatEmpty = container.querySelector("#chat-empty");
        if (chatEmpty) chatEmpty.remove();
        const estavaNoFundo = estaPertoDoFundo(container);
        const novas = mensagensFiltradas.slice(numBaloes);
        novas.forEach((msg) => adicionarBalaoChat(msg, false, false)); // com animação só na nova
        rolarFinalSeEstavaNoFundo(container, estavaNoFundo);
        return;
    }

    // Primeira carga ou troca de contato: redesenha tudo (sem rolar a cada mensagem para não dar efeito de "rolar todas")
    const chatEmpty = container.querySelector("#chat-empty");
    if (chatEmpty) chatEmpty.remove();
    container.innerHTML = "";
    mensagensFiltradas.forEach((msg) => adicionarBalaoChat(msg, false, true)); // sem animação
    rolarFinal(true); // instantâneo no redesenho completo para não parecer que "rola todas"
}

/** Chave estável para deduplicar mensagens (merge thread / polling). */
function chaveMensagemUnica(m) {
    if (!m) return "";
    if (m.id != null && String(m.id).length) return "id:" + String(m.id);
    const c = String(m.canal || "whatsapp").toLowerCase();
    const ridPart =
        c === "whatsapp"
            ? chaveUnreadRemoto("whatsapp", m.remote_id) || normalizarRemoteId(m.remote_id)
            : normalizarRemoteId(m.remote_id);
    const t = new Date(m.created_at || 0).getTime();
    const tKey = Number.isFinite(t) ? String(Math.floor(t / 1000)) : String(m.created_at || "");
    return String(ridPart || "") + "|" + tKey + "|" + (m.funcao || "") + "|" + String(m.conteudo || "").slice(0, 120);
}

function _tsMs(v) {
    const t = new Date(v || 0).getTime();
    return Number.isFinite(t) ? t : 0;
}

function _normText(v) {
    return String(v || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function existeDuplicataRecente(lista, msg, janelaMs) {
    if (!Array.isArray(lista) || !msg) return false;
    const janela = typeof janelaMs === "number" ? janelaMs : 20000;
    const rid = normalizarRemoteId(msg.remote_id);
    const funcao = msg.funcao || "";
    const texto = _normText(msg.conteudo);
    if (!rid || !funcao) return false;
    const tMsg = _tsMs(msg.created_at);
    for (let i = lista.length - 1; i >= 0; i--) {
        const cur = lista[i];
        if (!cur) continue;
        if (normalizarRemoteId(cur.remote_id) !== rid) continue;
        if ((cur.funcao || "") !== funcao) continue;
        if (_normText(cur.conteudo) !== texto) continue;
        if (Math.abs(_tsMs(cur.created_at) - tMsg) <= janela) return true;
    }
    return false;
}

/**
 * GET /api/mensagens/<canal> sem remote_id devolve 1 msg por conversa; ao fazer polling não podemos
 * substituir o histórico já carregado da conversa aberta.
 */
function mesclarListaComThreadAberto(prev, ordenadoLista, canal) {
    const c = canal || "whatsapp";
    if (!idRemotoAtivo || !Array.isArray(prev) || !Array.isArray(ordenadoLista)) {
        return ordenadoLista;
    }
    const threadAberto = prev.filter(
        (m) => mesmoContatoNoCanal(c, m.remote_id, idRemotoAtivo) && (m.canal || "whatsapp") === c
    );
    if (threadAberto.length === 0) {
        return ordenadoLista;
    }
    const keys = new Set(threadAberto.map(chaveMensagemUnica));
    const latestFromApi = ordenadoLista.find((m) => mesmoContatoNoCanal(c, m.remote_id, idRemotoAtivo));
    let merged = threadAberto.slice();
    if (latestFromApi) {
        const k = chaveMensagemUnica(latestFromApi);
        if (!keys.has(k)) {
            merged.push({ ...latestFromApi, canal: latestFromApi.canal || canal });
            keys.add(k);
        }
    }
    const outros = ordenadoLista.filter((m) => !mesmoContatoNoCanal(c, m.remote_id, idRemotoAtivo));
    const combinado = [...outros, ...merged].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
    const dedup = [];
    combinado.forEach((m) => {
        if (existeDuplicataRecente(dedup, m, 25000)) return;
        dedup.push(m);
    });
    return dedup;
}

/** Carrega contatos com mensagem de usuário (não lidos) por canal e preenche badges sem precisar clicar em cada canal. */
async function carregarContatosNaoLidos() {
    try {
        const res = await fetch("/api/mensagens/contatos-nao-lidos");
        const raw = await res.text();
        if (typeof raw === "string" && raw.trim().startsWith("<")) {
            window.location.href = "/?sessao=expirada";
            return;
        }
        if (!res.ok) return;
        let data;
        try { data = JSON.parse(raw); } catch (e) { return; }
        if (!data) return;
        ["whatsapp", "facebook", "instagram", "website"].forEach((c) => {
            unreadByChannel[c] = {};
            const ids = data[c];
            if (Array.isArray(ids) && ids.length) {
                ids.forEach((rid) => { unreadByChannel[c][chaveUnreadRemoto(c, rid)] = true; });
            }
        });
        atualizarBadgesCanais();
    } catch (e) {
        console.warn("[Chat] Erro ao carregar contatos não lidos:", e);
    }
}

async function carregarMensagens(canal) {
    erroCarregamentoChat = null;
    try {
        const res = await fetch(`/api/mensagens/${canal}`);
        const data = await (async () => {
            const text = await res.text();
            if (typeof text === "string" && text.trim().startsWith("<")) {
                window.location.href = "/?sessao=expirada";
                return [];
            }
            try {
                return JSON.parse(text);
            } catch (e) {
                if (res.status === 401) window.location.href = "/?sessao=expirada";
                throw e;
            }
        })();
        if (!res.ok) {
            const detalhe = (data && (data.erro || data.mensagem || data.message)) ? String(data.erro || data.mensagem || data.message) : "";
            if (res.status === 401) throw new Error("Sessão expirada. Faça login novamente.");
            throw new Error(detalhe || ("Erro " + res.status));
        }
        const novo = Array.isArray(data) ? data : [];
        const ordenado = [...novo].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
        const prev = mensagensGlobais;
        const eraPrimeiraCarga = prev.length === 0;
        // Só notificar mensagens "novas" quando estamos atualizando o MESMO canal (polling), não ao trocar de aba
        const mesmoCanal = canal === ultimoCanalCarregado;
        const msgsUserAntes = new Set(
            prev.filter((m) => (m.canal || "whatsapp") === canal && m.funcao === "user").map(chaveMensagemUnica)
        );
        const countAtivoAntes = idRemotoAtivo ? prev.filter((m) => mesmoContatoNoCanal(canal, m.remote_id, idRemotoAtivo)).length : 0;
        mensagensGlobais = mesclarListaComThreadAberto(prev, ordenado, canal);
        ultimoCanalCarregado = canal;
        if (!eraPrimeiraCarga && mesmoCanal) {
            ordenado.filter((m) => m.funcao === "user").forEach((m) => {
                if (msgsUserAntes.has(chaveMensagemUnica(m))) return;
                const ehConversaAberta = mesmoContatoNoCanal(canal, m.remote_id, idRemotoAtivo);
                if (!ehConversaAberta) {
                    marcarUnread(canal, m.remote_id);
                    tocarSomNotificacao();
                    if (document.hidden) mostrarNotificacaoDesktop("Nova mensagem", (m.conteudo || "").slice(0, 60) + (m.conteudo && m.conteudo.length > 60 ? "…" : ""));
                } else {
                    marcarLidoNoServidor(canal, m.remote_id);
                }
            });
        }
        // Só manter como "não lido" conversas que existem na lista atual (evita badge de chats que sumiram da timeline)
        const idsNaLista = new Set(
            mensagensGlobais.map((m) => chaveUnreadRemoto(m.canal || canal, m.remote_id))
        );
        if (unreadByChannel[canal]) {
            Object.keys(unreadByChannel[canal]).forEach((rid) => {
                if (!idsNaLista.has(rid)) delete unreadByChannel[canal][rid];
            });
        }
        atualizarBadgesCanais();
        renderizarListaContatos();
        const countAtivoDepois = idRemotoAtivo ? mensagensGlobais.filter((m) => mesmoContatoNoCanal(canal, m.remote_id, idRemotoAtivo)).length : 0;
        const temMensagemNova = countAtivoDepois > countAtivoAntes;
        atualizarAreaChatAberta(temMensagemNova);
    } catch (err) {
        console.error("Erro ao carregar histórico:", err);
        erroCarregamentoChat = err && err.message ? err.message : "Erro ao carregar. Tente novamente.";
        mensagensGlobais = [];
        renderizarListaContatos();
    }
}

function carregarWahaOverview() {
    fetch("/api/waha/chats/overview?limit=200")
        .then((r) => r.ok ? r.json() : { chats: [] })
        .then((d) => {
            const map = {};
            (d.chats || []).forEach((ch) => {
                if (ch.id) map[ch.id] = { name: ch.name || "", picture: ch.picture || null };
            });
            wahaChatsOverview = map;
            renderizarListaContatos();
        })
        .catch(() => {});
}

function setCanalAtivo(canal) {
    canalAtivo = canal;
    idRemotoAtivo = null;
    if (canal === "whatsapp") carregarWahaOverview();
    document.querySelectorAll(".canal-btn").forEach((btn) => {
        const isActive = btn.getAttribute("data-canal") === canal;
        btn.classList.toggle("bg-white", isActive);
        btn.classList.toggle("text-slate-800", isActive);
        btn.classList.toggle("shadow-sm", isActive);
        btn.classList.toggle("text-slate-500", !isActive);
    });
    const label = document.getElementById("canal-label");
    if (label) label.textContent = CANAL_LABELS[canal] || canal;
    carregarMensagens(canal);
    const container = document.getElementById("chat-container");
    if (container) {
        container.innerHTML = "";
        const wrap = document.createElement("div");
        wrap.id = "chat-empty";
        wrap.className = "h-full flex flex-col items-center justify-center text-slate-400";
        wrap.innerHTML = '<i class="fa-regular fa-comments text-5xl mb-4 opacity-30"></i><p class="text-sm font-medium">Mensagens aparecerão aqui</p><p class="text-xs mt-1">Selecione uma conversa ou aguarde novos contatos</p>';
        container.appendChild(wrap);
    }
    const chatNome = document.getElementById("chat-nome");
    if (chatNome) chatNome.textContent = "Selecione um contato";
    const headerNumero = document.getElementById("chat-numero");
    const headerNumeroPrefix = document.getElementById("chat-numero-prefix");
    if (headerNumero) { headerNumero.textContent = ""; headerNumero.classList.add("hidden"); }
    if (headerNumeroPrefix) headerNumeroPrefix.classList.add("hidden");
    const etiquetaWrap = document.getElementById("chat-etiqueta-wrap");
    if (etiquetaWrap) etiquetaWrap.classList.add("hidden");
    const btnAnexo = document.getElementById("btn-anexo");
    if (btnAnexo) btnAnexo.style.display = canal === "whatsapp" ? "" : "none";
    const btnMic = document.getElementById("btn-mic");
    if (btnMic) btnMic.style.display = canal === "whatsapp" ? "" : "none";
    if (gravandoAudio && mediaRecorderAudio && mediaRecorderAudio.state !== "inactive") {
        mostrarUIgravando(false);
        gravandoAudio = false;
        try { mediaRecorderAudio.stop(); } catch (_) {}
        mediaRecorderAudio = null;
        chunksAudio = [];
    }
    atualizarBadgesCanais();
}

function renderizarListaContatos() {
    const listaUl = document.getElementById("lista-contatos");
    if (!listaUl) return;

    if (erroCarregamentoChat) {
        listaUl.innerHTML = "<div class=\"p-6 text-center text-sm text-amber-700 bg-amber-50 border-b border-amber-100\"><i class=\"fas fa-exclamation-triangle mr-1\"></i> " + (erroCarregamentoChat || "Erro ao carregar.") + "</div>";
        return;
    }

    const contatosMap = {};
    mensagensGlobais.forEach((msg) => {
        contatosMap[msg.remote_id] = msg;
    });
    const contatosUnicos = Object.values(contatosMap).sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    const termoBusca = normalizarTextoBusca(termoBuscaContato);
    const contatosFiltrados = termoBusca
        ? contatosUnicos.filter((contato) => {
            const info = getContactInfo(contato);
            const nome = normalizarTextoBusca(info.nome || "");
            const numero = normalizarTextoBusca(String(contato.remote_id || "").replace(/@.*$/, ""));
            return nome.includes(termoBusca) || numero.includes(termoBusca);
        })
        : contatosUnicos;

    if (contatosUnicos.length === 0) {
        listaUl.innerHTML = "<div class=\"p-8 text-center text-slate-400 text-xs\"><i class=\"fa-regular fa-comments mb-2 text-lg\"></i><br>Nenhuma conversa ainda.<br><span class=\"text-slate-300\">As conversas aparecerão aqui.</span></div>";
        return;
    }
    if (contatosFiltrados.length === 0) {
        listaUl.innerHTML = "<div class=\"p-8 text-center text-slate-400 text-xs\"><i class=\"fa-solid fa-magnifying-glass mb-2 text-lg\"></i><br>Nenhum contato encontrado.</div>";
        return;
    }

    listaUl.innerHTML = "";
    contatosFiltrados.forEach((contato) => {
        const info = getContactInfo(contato);
        const eAtivo = Boolean(idRemotoAtivo && mesmoContatoNoCanal(canalAtivo, contato.remote_id, idRemotoAtivo));
        const temUnread = !!(unreadByChannel[canalAtivo] && unreadByChannel[canalAtivo][chaveUnreadRemoto(canalAtivo, contato.remote_id)]);
        const rid = contato.remote_id;
        const li = document.createElement("li");
        li.className = `border-b border-slate-100 transition-all ${eAtivo ? "bg-blue-50 border-r-4 border-blue-500" : ""}`;
        li.setAttribute("data-remote-id", rid);

        const row = document.createElement("div");
        row.className = "p-3 flex items-center gap-3 cursor-pointer hover:bg-slate-50";
        row.onclick = () => abrirChat(rid);

        const imgWrap = document.createElement("div");
        imgWrap.className = "relative flex-shrink-0";
        const img = document.createElement("img");
        img.src = info.foto;
        img.className = "w-10 h-10 rounded-full bg-slate-200 object-cover";
        img.alt = info.nome;
        imgWrap.appendChild(img);
        if (temUnread) {
            const dot = document.createElement("span");
            dot.className = "chat-badge-dot absolute -top-0.5 -right-0.5";
            imgWrap.appendChild(dot);
        }

        const wrapper = document.createElement("div");
        wrapper.className = "flex-1 min-w-0";
        const linhaTopo = document.createElement("div");
        linhaTopo.className = "flex justify-between items-center";
        const spanNome = document.createElement("span");
        spanNome.className = "text-slate-900 text-sm font-semibold truncate";
        spanNome.textContent = info.nome;
        const spanHora = document.createElement("span");
        spanHora.className = "text-[10px] text-slate-400";
        spanHora.textContent = formatHora(contato.created_at);
        linhaTopo.appendChild(spanNome);
        linhaTopo.appendChild(spanHora);
        const pPreview = document.createElement("p");
        pPreview.className = "text-xs text-slate-500 truncate";
        const prevText = contato.anexo_url
            ? (ehImagemAnexo(contato.anexo_tipo) ? "📷 Imagem" : (contato.anexo_tipo || "").toLowerCase().startsWith("audio/") ? "🎤 Áudio" : "📎 " + (contato.anexo_nome || "Arquivo"))
            : (pareceBase64Imagem(contato.conteudo) ? "📷 Imagem" : (contato.conteudo || ""));
        pPreview.textContent = prevText;
        wrapper.appendChild(linhaTopo);
        wrapper.appendChild(pPreview);
        row.appendChild(imgWrap);
        row.appendChild(wrapper);

        const btnToggle = document.createElement("button");
        btnToggle.type = "button";
        btnToggle.className = "flex-shrink-0 p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition";
        btnToggle.setAttribute("aria-label", "Ver número");
        btnToggle.innerHTML = '<i class="fas fa-chevron-down text-xs lead-chevron"></i>';
        btnToggle.onclick = (e) => {
            e.stopPropagation();
            const detalhes = li.querySelector(".lead-detalhes");
            if (detalhes) {
                detalhes.classList.toggle("hidden");
                btnToggle.querySelector("i").classList.toggle("fa-chevron-down", detalhes.classList.contains("hidden"));
                btnToggle.querySelector("i").classList.toggle("fa-chevron-up", !detalhes.classList.contains("hidden"));
            }
        };
        row.appendChild(btnToggle);
        li.appendChild(row);

        const detalhes = document.createElement("div");
        detalhes.className = "lead-detalhes hidden px-3 pb-3 pt-0";
        detalhes.innerHTML = `<p class="text-xs text-slate-500 font-mono">${String(rid).replace(/@.*$/, "")}</p>`;
        li.appendChild(detalhes);

        listaUl.appendChild(li);
    });
}

/** Remove balões e redesenha a conversa atual (mantém #chat-load-more). */
function redesenharBaloesConversaAberta(remote_id) {
    const container = document.getElementById("chat-container");
    if (!container) return;
    if (!idRemotoAtivo || !mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) return;
    container.querySelectorAll(".msg-balao").forEach((el) => el.remove());
    const mensagensFiltradas = mensagensGlobais.filter(
        (m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id)
    );
    mensagensFiltradas.forEach((msg) => adicionarBalaoChat(msg, false, true));
    atualizarBotaoCarregarMais(remote_id);
    rolarFinal(true);
}

/**
 * Busca até 100 mensagens recentes da conversa e substitui o cache local deste remote_id.
 */
async function carregarHistoricoInicialConversa(remote_id) {
    const ridKey = chaveUnreadRemoto(canalAtivo, remote_id);
    const wrap = document.getElementById("chat-load-more");
    try {
        const params = new URLSearchParams({ remote_id: String(remote_id), limit: String(LIMITE_HISTORICO_INICIAL) });
        const res = await fetch(`/api/mensagens/${canalAtivo}?${params}`);
        const text = await res.text();
        if (typeof text === "string" && text.trim().startsWith("<")) {
            window.location.href = "/?sessao=expirada";
            return;
        }
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (_) {
            parsed = [];
        }
        if (!res.ok) {
            const errMsg =
                parsed && typeof parsed === "object" && !Array.isArray(parsed)
                    ? parsed.erro || parsed.mensagem || parsed.message
                    : null;
            throw new Error(errMsg ? String(errMsg) : "Erro ao carregar histórico");
        }
        const data = Array.isArray(parsed) ? parsed : [];
        const ordenadas = data
            .map((m) => ({ ...m, canal: m.canal || canalAtivo }))
            .sort(compararMensagemHistorico);

        if (!idRemotoAtivo || !mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) return;

        const outras = mensagensGlobais.filter((m) => !mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id));
        mensagensGlobais = [...outras, ...ordenadas].sort(compararMensagemHistorico);
        semMaisAntigasPorRemote[ridKey] = ordenadas.length < LIMITE_HISTORICO_INICIAL;
        redesenharBaloesConversaAberta(remote_id);
    } catch (e) {
        console.error("[Chat] carregarHistoricoInicialConversa:", e);
        if (!idRemotoAtivo || !mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) return;
        if (wrap) {
            wrap.classList.remove("pointer-events-none");
            wrap.innerHTML = "<span class=\"text-xs text-amber-700\">Não foi possível carregar o histórico. Tente novamente.</span>";
        }
        const fallback = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id));
        if (fallback.length) {
            redesenharBaloesConversaAberta(remote_id);
        }
    }
}

function abrirChat(remote_id) {
    idRemotoAtivo = remote_id;
    console.log("[Chat] Contato selecionado", { remote_id, canal: canalAtivo });
    limparUnreadCanalAoAbrir(remote_id);
    window.dispatchEvent(new CustomEvent("agenteia-conversa-lida"));
    marcarLidoNoServidor(canalAtivo, remote_id, { immediate: true });
    const ultimaMsg = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id)).pop();
    const info = getContactInfo(ultimaMsg || { remote_id, canal: canalAtivo });

    const headerNome = document.getElementById("chat-nome");
    if (headerNome) { headerNome.textContent = info.nome; headerNome.title = info.nome; }
    const headerFoto = document.getElementById("chat-foto-header");
    if (headerFoto) {
        headerFoto.src = info.foto;
        headerFoto.alt = info.nome;
    }
    const headerNumero = document.getElementById("chat-numero");
    const headerNumeroPrefix = document.getElementById("chat-numero-prefix");
    if (headerNumero) {
        headerNumero.textContent = remote_id ? String(remote_id).replace(/@.*$/, "") : "";
        headerNumero.classList.toggle("hidden", !remote_id);
        if (headerNumeroPrefix) headerNumeroPrefix.classList.toggle("hidden", !remote_id);
    }

    const etiquetaWrap = document.getElementById("chat-etiqueta-wrap");
    const setorSelect = document.getElementById("chat-setor");
    if (etiquetaWrap) etiquetaWrap.classList.remove("hidden");
    if (setorSelect) {
        currentSetorEstado = "atendimento_ia";
        setorSelect.value = "";
        updateIndicadorIA();
        fetch("/api/setores")
            .then((r) => r.ok ? r.json() : { setores: [] })
            .then((data) => {
                const setores = (data && data.setores) || [];
                const opts = ["<option value=\"\">Geral</option>"].concat(
                    setores.filter((s) => s.ativo !== false).map((s) => "<option value=\"" + (s.id || "").replace(/"/g, "&quot;") + "\">" + (s.nome || "Setor").replace(/</g, "&lt;") + "</option>")
                );
                setorSelect.innerHTML = opts.join("");
                return fetch("/api/conversacao-setor?remote_id=" + encodeURIComponent(remote_id) + "&canal=" + encodeURIComponent(canalAtivo));
            })
            .then((r) => r.json())
            .then((d) => {
                currentSetorEstado = (d.setor || "atendimento_ia").toLowerCase();
                setorSelect.value = d.setor_id || "";
                if (setorSelect.dataset) setorSelect.dataset.lastValue = setorSelect.value;
                updateIndicadorIA();
            })
            .catch(() => {});
    }

    const container = document.getElementById("chat-container");
    if (!container) return;
    container.innerHTML = "";
    const loadMoreWrap = document.createElement("div");
    loadMoreWrap.id = "chat-load-more";
    loadMoreWrap.className = "flex flex-col items-center justify-center gap-1 py-3 border-b border-slate-100";
    loadMoreWrap.innerHTML = "<span class=\"text-xs text-slate-400\"><i class=\"fas fa-spinner fa-spin mr-1\"></i> Carregando histórico...</span>";
    container.appendChild(loadMoreWrap);
    renderizarListaContatos();
    bindScrollCarregarAntigas(container, remote_id);
    void carregarHistoricoInicialConversa(remote_id);
    if (typeof window.agenteiaMobileChatView === "function" && window.innerWidth < 640) {
        window.agenteiaMobileChatView(true);
    }
}

/** True se o conteúdo parece ser imagem em base64 (evita exibir texto gigante na bolha). */
function pareceBase64Imagem(conteudo) {
    if (!conteudo || typeof conteudo !== "string" || conteudo.length < 80) return false;
    const s = conteudo.trim();
    return s.startsWith("/9j/") || s.startsWith("data:image/") || s.startsWith("iVBORw0KGgo");
}

function ehImagemAnexo(tipo) {
    return (tipo || "").toLowerCase().startsWith("image/");
}

/** Quando uma imagem termina de carregar, mantém o fundo se o usuário ainda estiver no fim (scrollHeight tardio). */
function registrarImagemScrollSeNoFundo(img, container) {
    if (!img || !container) return;
    img.addEventListener(
        "load",
        function onLoad() {
            img.removeEventListener("load", onLoad);
            if (estaPertoDoFundo(container)) rolarFinal(true);
        },
        { once: true }
    );
}

function adicionarBalaoChat(msg, scrollAgora, semAnimacao, prepend) {
    if (typeof scrollAgora === "undefined") scrollAgora = true;
    if (typeof semAnimacao === "undefined") semAnimacao = false;
    if (typeof prepend === "undefined") prepend = false;
    const container = document.getElementById("chat-container");
    if (!container) return;
    const estavaNoFundoAntes = !prepend && estaPertoDoFundo(container);
    const ehEntrada = msg.funcao === "user";
    let conteudo = msg.conteudo || "";
    let atendenteNome = msg.atendente_nome_snapshot || null;
    // Não interpretar "Nome: texto" em payloads JSON (ex.: fluxo website com botões).
    // O primeiro ": " em {"text": "...", "buttons": [...]} quebrava o JSON e o painel mostrava o texto cru.
    if (!ehEntrada && typeof conteudo === "string") {
        const pareceJsonObjeto = conteudo.trim().startsWith("{");
        if (!pareceJsonObjeto) {
            if (atendenteNome) {
                const p2 = "[" + atendenteNome + "]: ";
                const p1 = atendenteNome + ": ";
                if (conteudo.startsWith(p2)) conteudo = conteudo.slice(p2.length).trim();
                else if (conteudo.startsWith(p1)) conteudo = conteudo.slice(p1.length).trim();
            } else if (/^[^[\]:]+:\s*/.test(conteudo)) {
                const idx = conteudo.indexOf(": ");
                if (idx > 0) {
                    atendenteNome = conteudo.slice(0, idx).trim();
                    conteudo = conteudo.slice(idx + 2).trim();
                }
            }
        }
    }
    const displayConteudo = conteudo;
    const anim = semAnimacao ? "" : " animate-fade-in";
    const div = document.createElement("div");
    div.className = `msg-balao flex w-full min-w-0 ${ehEntrada ? "justify-start" : "justify-end"} mb-4${anim}`;
    const wrapperCol = document.createElement("div");
    wrapperCol.className = "flex flex-col items-end min-w-0 max-w-[min(100%,32rem)] sm:max-w-[85%]";
    if (ehEntrada) wrapperCol.classList.add("items-start");
    const estilo = ehEntrada
        ? "bg-white border border-slate-200 text-slate-700 rounded-2xl rounded-tl-none shadow-sm"
        : "bg-slate-800 text-white shadow-md rounded-2xl rounded-tr-none";
    const bubble = document.createElement("div");
    bubble.className = `p-3 px-4 text-sm break-words max-w-full min-w-0 ${estilo}`;
    if (!ehEntrada && atendenteNome) {
        const nomeLine = document.createElement("div");
        nomeLine.className = "font-semibold text-slate-200 text-xs mb-1";
        nomeLine.textContent = atendenteNome;
        bubble.appendChild(nomeLine);
    }

    const anexoUrl = msg.anexo_url || "";
    const anexoNome = msg.anexo_nome || "";
    const anexoTipo = msg.anexo_tipo || "";

    if (anexoUrl) {
        if (ehImagemAnexo(anexoTipo)) {
            const img = document.createElement("img");
            img.src = anexoUrl;
            img.alt = anexoNome || "Imagem";
            img.loading = "lazy";
            img.style.maxHeight = "200px";
            img.style.borderRadius = "8px";
            img.style.display = "block";
            registrarImagemScrollSeNoFundo(img, container);
            bubble.appendChild(img);
            const link = document.createElement("a");
            link.href = anexoUrl;
            link.download = anexoNome || "imagem";
            link.className = "text-xs mt-2 inline-block " + (ehEntrada ? "text-slate-600 hover:text-slate-800" : "text-slate-300 hover:text-white");
            link.textContent = "Baixar imagem";
            bubble.appendChild(link);
        } else if ((anexoTipo || "").toLowerCase().startsWith("audio/")) {
            const audio = document.createElement("audio");
            audio.controls = true;
            audio.preload = "metadata";
            audio.src = anexoUrl;
            audio.className = "max-w-full mt-1";
            audio.style.maxWidth = "280px";
            bubble.appendChild(audio);
            const link = document.createElement("a");
            link.href = anexoUrl;
            link.download = anexoNome || "audio";
            link.className = "text-xs mt-2 inline-block " + (ehEntrada ? "text-slate-600 hover:text-slate-800" : "text-slate-300 hover:text-white");
            link.textContent = "Baixar áudio";
            bubble.appendChild(link);
        } else {
            const link = document.createElement("a");
            link.href = anexoUrl;
            link.download = anexoNome || "arquivo";
            link.target = "_blank";
            link.rel = "noopener";
            link.className = "inline-flex items-center gap-1 " + (ehEntrada ? "text-blue-600 hover:underline" : "text-slate-200 hover:text-white");
            link.innerHTML = "📎 " + (anexoNome || "Arquivo") + " – Baixar";
            bubble.appendChild(link);
        }
        if (displayConteudo && displayConteudo !== "[imagem enviada]" && displayConteudo !== "[arquivo enviado]" && displayConteudo !== "[áudio enviado]") {
            const p = document.createElement("p");
            p.className = "mt-2 mb-0 msg-text";
            appendLinkifiedText(p, displayConteudo, ehEntrada ? "text-blue-700 hover:text-blue-800" : "text-emerald-200 hover:text-white");
            bubble.appendChild(p);
        }
    } else if (pareceBase64Imagem(displayConteudo)) {
        const src = displayConteudo.trim().startsWith("data:") ? displayConteudo.trim() : "data:image/jpeg;base64," + displayConteudo.trim();
        const img = document.createElement("img");
        img.src = src;
        img.alt = "Imagem";
        img.loading = "lazy";
        img.style.maxHeight = "200px";
        img.style.borderRadius = "8px";
        img.style.display = "block";
        registrarImagemScrollSeNoFundo(img, container);
        bubble.appendChild(img);
    } else if (displayConteudo) {
        let parsed = null;
        try {
            if (typeof displayConteudo === "string" && displayConteudo.trim().startsWith("{")) {
                parsed = JSON.parse(displayConteudo);
            }
        } catch (_) {}
        if (parsed && typeof parsed.text !== "undefined" && Array.isArray(parsed.buttons) && parsed.buttons.length) {
            const p = document.createElement("p");
            p.className = "mb-2 msg-text";
            appendLinkifiedText(p, parsed.text || "", ehEntrada ? "text-blue-700 hover:text-blue-800" : "text-emerald-200 hover:text-white");
            bubble.appendChild(p);
            const btnWrap = document.createElement("div");
            btnWrap.className = "flex flex-wrap gap-2";
            parsed.buttons.forEach((b) => {
                const label = (b && (b.title || b.label || b.id)) || "";
                if (!label) return;
                const span = document.createElement("span");
                span.className = "inline-block px-3 py-1.5 rounded-lg text-xs font-medium bg-white/20 cursor-default select-none";
                span.textContent = label;
                btnWrap.appendChild(span);
            });
            bubble.appendChild(btnWrap);
        } else {
            const span = document.createElement("span");
            span.className = "msg-text";
            appendLinkifiedText(span, String(displayConteudo || ""), ehEntrada ? "text-blue-700 hover:text-blue-800" : "text-emerald-200 hover:text-white");
            bubble.appendChild(span);
        }
    }
    wrapperCol.appendChild(bubble);
    const horaSpan = document.createElement("span");
    horaSpan.className = "text-[10px] mt-1 " + (ehEntrada ? "text-slate-400" : "text-slate-400");
    horaSpan.textContent = formatDataHoraBR(msg.created_at);
    horaSpan.setAttribute("title", msg.created_at || "");
    wrapperCol.appendChild(horaSpan);
    div.appendChild(wrapperCol);
    if (prepend) {
        const loadMore = container.querySelector("#chat-load-more");
        const ref = loadMore ? loadMore.nextElementSibling : container.firstChild;
        container.insertBefore(div, ref);
    } else {
        container.appendChild(div);
    }
    if (scrollAgora && !prepend && estavaNoFundoAntes) rolarFinal(true);
}

function atualizarBotaoCarregarMais(remote_id) {
    const wrap = document.getElementById("chat-load-more");
    if (!wrap) return;
    const rid = chaveUnreadRemoto(canalAtivo, remote_id);
    if (semMaisAntigasPorRemote[rid]) {
        wrap.innerHTML = "<span class=\"text-xs text-slate-400\">Não há mais mensagens antigas</span>";
        wrap.classList.add("pointer-events-none");
        return;
    }
    wrap.classList.remove("pointer-events-none");
    wrap.innerHTML = "";
    const hint = document.createElement("span");
    hint.className = "text-[10px] text-slate-400 text-center px-2";
    hint.textContent = "Role para o topo para carregar o histórico";
    wrap.appendChild(hint);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "text-xs text-slate-500 hover:text-slate-700 py-1 px-3 rounded";
    btn.setAttribute("aria-label", "Carregar mensagens antigas");
    btn.textContent = "Carregar mais";
    btn.onclick = () => carregarMensagensAntigas(remote_id);
    wrap.appendChild(btn);
}

function bindScrollCarregarAntigas(container, remote_id) {
    if (!container || !remote_id) return;
    if (chatScrollHandler) {
        container.removeEventListener("scroll", chatScrollHandler);
        chatScrollHandler = null;
    }
    let raf = null;
    chatScrollHandler = () => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
            raf = null;
            if (loadingMaisAntigas) return;
            if (!idRemotoAtivo || !mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) return;
            if (semMaisAntigasPorRemote[chaveUnreadRemoto(canalAtivo, remote_id)]) return;
            const mensagensDesteChat = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id));
            if (mensagensDesteChat.length === 0) return;
            if (container.scrollTop < 100) carregarMensagensAntigas(remote_id);
        });
    };
    container.addEventListener("scroll", chatScrollHandler, { passive: true });
}

async function carregarMensagensAntigas(remote_id) {
    const rid = chaveUnreadRemoto(canalAtivo, remote_id);
    if (loadingMaisAntigas || semMaisAntigasPorRemote[rid]) return;
    const mensagensDesteChat = mensagensGlobais.filter((m) => mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id));
    if (mensagensDesteChat.length === 0) return;
    const ordenadas = [...mensagensDesteChat].sort(compararMensagemHistorico);
    const maisAntiga = ordenadas[0];
    const before = maisAntiga.created_at;
    if (!before) return;

    const wrap = document.getElementById("chat-load-more");
    if (wrap) {
        wrap.innerHTML = "<span class=\"text-xs text-slate-400\"><i class=\"fas fa-spinner fa-spin mr-1\"></i> Carregando...</span>";
        wrap.classList.add("pointer-events-none");
    }
    loadingMaisAntigas = true;
    try {
        const params = new URLSearchParams({
            before: String(before),
            remote_id: String(maisAntiga.remote_id || remote_id),
            limit: String(LIMITE_PAGINA_ANTIGA)
        });
        if (maisAntiga.id != null && String(maisAntiga.id).length) {
            params.set("before_id", String(maisAntiga.id));
        }
        const res = await fetch(`/api/mensagens/${canalAtivo}?${params}`);
        const raw = await res.text();
        if (raw.trim().startsWith("<")) {
            window.location.href = "/?sessao=expirada";
            return;
        }
        let parsed;
        try {
            parsed = JSON.parse(raw);
        } catch (_) {
            parsed = null;
        }
        if (!res.ok) {
            const errMsg =
                parsed && typeof parsed === "object" && !Array.isArray(parsed)
                    ? parsed.erro || parsed.mensagem || parsed.message
                    : null;
            if (errMsg) showPainelToast(String(errMsg), "error");
            return;
        }
        if (!Array.isArray(parsed)) {
            showPainelToast("Resposta inválida ao carregar o histórico.", "error");
            return;
        }
        const data = parsed;
        if (data.length < LIMITE_PAGINA_ANTIGA) {
            semMaisAntigasPorRemote[rid] = true;
        }

        const existentes = new Set(
            mensagensDesteChat.map((m) => (m.id != null && String(m.id).length ? String(m.id) : null)).filter(Boolean)
        );
        const dataSemDuplicar = data.filter((m) => {
            if (m.id == null || !String(m.id).length) return true;
            return !existentes.has(String(m.id));
        });
        const novasAntigas = dataSemDuplicar
            .map((m) => ({ ...m, canal: m.canal || canalAtivo }))
            .sort(compararMensagemHistorico);
        const outras = mensagensGlobais.filter((m) => !mesmoContatoNoCanal(canalAtivo, m.remote_id, remote_id));
        const todasDesteChat = [...novasAntigas, ...mensagensDesteChat];
        mensagensGlobais = [...outras, ...todasDesteChat].sort(compararMensagemHistorico);

        const container = document.getElementById("chat-container");
        if (!container || !idRemotoAtivo || !mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) return;
        const oldScrollHeight = container.scrollHeight;
        const oldScrollTop = container.scrollTop;
        novasAntigas.forEach((msg) => adicionarBalaoChat(msg, false, true, true));
        const aplicarAncoraHistorico = () => {
            if (!container.isConnected) return;
            container.scrollTop = container.scrollHeight - oldScrollHeight + oldScrollTop;
        };
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                aplicarAncoraHistorico();
                let ro = null;
                try {
                    ro = new ResizeObserver(() => {
                        aplicarAncoraHistorico();
                    });
                    ro.observe(container);
                    setTimeout(() => {
                        if (ro) {
                            ro.disconnect();
                            ro = null;
                        }
                    }, 900);
                } catch (_) {
                    aplicarAncoraHistorico();
                }
            });
        });
    } catch (e) {
        console.error("[Chat] carregarMensagensAntigas:", e);
        showPainelToast("Não foi possível carregar mensagens antigas.", "error");
    } finally {
        loadingMaisAntigas = false;
        if (idRemotoAtivo && mesmoContatoNoCanal(canalAtivo, remote_id, idRemotoAtivo)) {
            atualizarBotaoCarregarMais(remote_id);
        }
    }
}

async function enviarAnexo() {
    const inputFile = document.getElementById("input-anexo");
    if (!inputFile || !inputFile.files || !inputFile.files.length) return;
    if (!idRemotoAtivo) {
        showPainelToast("Selecione um contato para enviar o arquivo.", "warn");
        inputFile.value = "";
        return;
    }
    if (canalAtivo !== "whatsapp") {
        showPainelToast("Envio de imagens e documentos está disponível apenas no WhatsApp.", "warn");
        inputFile.value = "";
        return;
    }
    const file = inputFile.files[0];
    const inputMsg = document.getElementById("input-msg");
    const texto = (inputMsg && inputMsg.value) ? inputMsg.value.trim() : "";
    const form = new FormData();
    form.append("remote_id", idRemotoAtivo);
    form.append("canal", "whatsapp");
    form.append("texto", texto);
    form.append("file", file);
    inputFile.value = "";
    if (inputMsg) {
        inputMsg.value = "";
        autoResizeInputMsg(inputMsg);
    }
    try {
        const res = await fetch("/api/enviar-midia", { method: "POST", credentials: "same-origin", body: form });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.status === "sucesso") {
            const conteudo = texto || (file.type.startsWith("audio/") ? "[áudio enviado]" : file.type.startsWith("image/") ? "[imagem enviada]" : "[arquivo enviado]");
            const msgEnviada = {
                remote_id: idRemotoAtivo,
                canal: canalAtivo,
                funcao: "assistant",
                conteudo: conteudo,
                anexo_url: data.anexo_url || "",
                anexo_nome: file.name || "",
                anexo_tipo: file.type || "",
                created_at: new Date().toISOString()
            };
            mensagensGlobais.push(msgEnviada);
            adicionarBalaoChat(msgEnviada, false);
            rolarFinal(true);
        } else {
            const msg = data.mensagem || data.message || "Falha ao enviar arquivo.";
            showPainelToast(msg, "error");
        }
    } catch (e) {
        console.error("[Chat] Erro ao enviar anexo:", e);
        showPainelToast("Erro ao enviar. Verifique a conexão.", "error");
    }
}

async function enviarClipboardAnexo() {
    if (!pendingClipboardFile) return;
    if (!idRemotoAtivo) {
        showPainelToast("Selecione um contato para enviar o anexo.", "warn");
        pendingClipboardFile = null;
        return;
    }
    if (canalAtivo !== "whatsapp") {
        showPainelToast("Envio de imagens e documentos está disponível apenas no WhatsApp.", "warn");
        pendingClipboardFile = null;
        const inputMsg = document.getElementById("input-msg");
        if (inputMsg) {
            inputMsg.value = "";
            if (inputMsgPlaceholderOriginal) inputMsg.setAttribute("placeholder", inputMsgPlaceholderOriginal);
            autoResizeInputMsg(inputMsg);
        }
        return;
    }

    const inputMsg = document.getElementById("input-msg");
    const texto = (inputMsg && inputMsg.value) ? inputMsg.value.trim() : "";
    const file = pendingClipboardFile;
    pendingClipboardFile = null;
    if (inputMsg) {
        inputMsg.value = "";
        if (inputMsgPlaceholderOriginal) inputMsg.setAttribute("placeholder", inputMsgPlaceholderOriginal);
        autoResizeInputMsg(inputMsg);
    }

    const form = new FormData();
    form.append("remote_id", idRemotoAtivo);
    form.append("canal", "whatsapp");
    form.append("texto", texto);
    form.append("file", file);

    try {
        const res = await fetch("/api/enviar-midia", { method: "POST", credentials: "same-origin", body: form });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.status === "sucesso") {
            const conteudo =
                texto ||
                (file.type.startsWith("audio/") ? "[áudio enviado]" :
                    file.type.startsWith("image/") ? "[imagem enviada]" :
                        "[arquivo enviado]");

            const msgEnviada = {
                remote_id: idRemotoAtivo,
                canal: canalAtivo,
                funcao: "assistant",
                conteudo: conteudo,
                anexo_url: data.anexo_url || "",
                anexo_nome: file.name || "clipboard.png",
                anexo_tipo: file.type || "",
                created_at: new Date().toISOString()
            };

            mensagensGlobais.push(msgEnviada);
            adicionarBalaoChat(msgEnviada, false);
            rolarFinal(true);
        } else {
            const msg = data.mensagem || data.message || "Falha ao enviar imagem.";
            showPainelToast(msg, "error");
        }
    } catch (e) {
        console.error("[Chat] Erro ao enviar anexo do clipboard:", e);
        showPainelToast("Erro ao enviar. Verifique a conexão.", "error");
    }
}

function mostrarUIgravando(mostrar) {
    const label = document.getElementById("gravando-label");
    const btnParar = document.getElementById("btn-parar-audio");
    if (label) label.classList.toggle("hidden", !mostrar);
    if (label) label.style.display = mostrar ? "inline-flex" : "none";
    if (btnParar) btnParar.classList.toggle("hidden", !mostrar);
}

async function startRecordingAudio() {
    if (!idRemotoAtivo || canalAtivo !== "whatsapp") {
        showPainelToast("Selecione um contato no WhatsApp para enviar áudio.", "warn");
        return;
    }
    if (gravandoAudio) return;
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
        mediaRecorderAudio = new MediaRecorder(stream);
        chunksAudio = [];
        mediaRecorderAudio.ondataavailable = (e) => { if (e.data.size > 0) chunksAudio.push(e.data); };
        mediaRecorderAudio.onstop = () => {
            stream.getTracks().forEach((t) => t.stop());
        };
        mediaRecorderAudio.start(200);
        gravandoAudio = true;
        mostrarUIgravando(true);
    } catch (e) {
        console.error("[Chat] Erro ao acessar microfone:", e);
        showPainelToast("Não foi possível acessar o microfone. Verifique as permissões do navegador.", "error");
    }
}

async function stopAndSendRecordingAudio() {
    if (!gravandoAudio || !mediaRecorderAudio || mediaRecorderAudio.state === "inactive") {
        mostrarUIgravando(false);
        gravandoAudio = false;
        return;
    }
    mediaRecorderAudio.stop();
    gravandoAudio = false;
    mostrarUIgravando(false);
    const blob = new Blob(chunksAudio, { type: "audio/webm" });
    mediaRecorderAudio = null;
    chunksAudio = [];
    if (blob.size < 1000) {
        showPainelToast("Gravação muito curta. Tente novamente.", "warn");
        return;
    }
    const form = new FormData();
    form.append("remote_id", idRemotoAtivo);
    form.append("canal", "whatsapp");
    form.append("texto", "");
    const file = new File([blob], "voice.webm", { type: "audio/webm" });
    form.append("file", file);
    try {
        const res = await fetch("/api/enviar-midia", { method: "POST", credentials: "same-origin", body: form });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.status === "sucesso") {
            const msgEnviada = {
                remote_id: idRemotoAtivo,
                canal: canalAtivo,
                funcao: "assistant",
                conteudo: "[áudio enviado]",
                anexo_url: data.anexo_url || "",
                anexo_nome: "voice.webm",
                anexo_tipo: "audio/webm",
                created_at: new Date().toISOString()
            };
            mensagensGlobais.push(msgEnviada);
            adicionarBalaoChat(msgEnviada, false);
            rolarFinal(true);
        } else {
            const msg = data.mensagem || data.message || "Falha ao enviar áudio.";
            showPainelToast(msg, "error");
        }
    } catch (e) {
        console.error("[Chat] Erro ao enviar áudio:", e);
        showPainelToast("Erro ao enviar. Verifique a conexão.", "error");
    }
}

async function enviarMensagemManual() {
    const input = document.getElementById("input-msg");
    if (!input || !idRemotoAtivo) {
        return;
    }

    const texto = input.value.trim();
    // Se o usuário colou uma imagem no clipboard, envie como mídia (prioridade).
    if (pendingClipboardFile) {
        await enviarClipboardAnexo();
        return;
    }
    if (!texto) return;
    input.value = "";
    autoResizeInputMsg(input);

    if (canalAtivo === "website") {
        try {
            const res = await fetch("/api/embed/send", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: idRemotoAtivo, texto: texto })
            });
            if (res.ok) {
                mensagensGlobais.push({
                    remote_id: idRemotoAtivo,
                    canal: "website",
                    funcao: "assistant",
                    conteudo: texto,
                    created_at: new Date().toISOString()
                });
                adicionarBalaoChat(
                    {
                        remote_id: idRemotoAtivo,
                        canal: "website",
                        funcao: "assistant",
                        conteudo: texto
                    },
                    false
                );
                rolarFinal(true);
            } else {
                console.error("❌ Erro ao enviar:", await res.json());
            }
        } catch (e) {
            console.error("❌ Erro técnico:", e);
        }
        return;
    }

    const canalEnvio = canalAtivo === "facebook" ? "facebook" : canalAtivo === "instagram" ? "instagram" : "whatsapp";
    const payload = { remote_id: idRemotoAtivo, texto: texto, canal: canalEnvio };
    // Mensagem enviada pelo atendente = assistant (direita). user = mensagem do cliente (esquerda).
    const msgEnviada = {
        remote_id: idRemotoAtivo,
        canal: canalAtivo,
        funcao: "assistant",
        conteudo: texto,
        created_at: new Date().toISOString(),
        atendente_nome_snapshot: typeof window.CHAT_ATENDENTE_NOME !== "undefined" ? window.CHAT_ATENDENTE_NOME : undefined
    };
    mensagensGlobais.push(msgEnviada);
    adicionarBalaoChat(msgEnviada, false);
    rolarFinal(true);
    console.log("[Chat] Enviando mensagem", { canal: canalEnvio, remote_id: idRemotoAtivo, texto_len: texto.length });
    try {
        const res = await fetch("/api/enviar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload)
        });
        console.log("[Chat] Resposta api/enviar", res.status, res.statusText);
        if (res.ok) {
            console.log("[Chat] Mensagem exibida no chat (assistant).");
        } else {
            mensagensGlobais.pop(); // remove a mensagem otimista
            const container = document.getElementById("chat-container");
            const ultimoBalao = container && container.querySelector(".msg-balao:last-child");
            if (ultimoBalao) ultimoBalao.remove();
            const err = await res.json().catch(() => ({}));
            const msg = err.mensagem || err.message || err.erro || "Falha ao enviar. Verifique Conexões.";
            console.error("[Chat] api/enviar 400 –", msg, "| body:", err);
            showPainelToast(msg, "error");
        }
    } catch (error) {
        console.error("[Chat] Erro ao chamar api/enviar:", error);
        showPainelToast("Erro ao enviar. Verifique a conexão.", "error");
    }
}

// Atualização em tempo real: polling a cada 3s (fallback) + SocketIO
let intervaloPolling = null;
const INTERVALO_POLLING_MS = 3000;

function iniciarPollingMensagens() {
    if (intervaloPolling) return;
    intervaloPolling = setInterval(() => {
        carregarMensagens(canalAtivo);
    }, INTERVALO_POLLING_MS);
}

// Ao reconectar o SocketIO, atualiza a lista na hora
socket.on("connect", () => {
    carregarMensagens(canalAtivo);
});

socket.on("disconnect", () => {
    // Polling continua rodando; ao reconectar, "connect" chama carregarMensagens
});

function bindUnlockAudioOnFirstGesture() {
    const events = ["click", "keydown", "touchstart"];
    const once = () => {
        unlockAudioContext();
        events.forEach((ev) => document.removeEventListener(ev, once));
    };
    events.forEach((ev) => document.addEventListener(ev, once, { passive: true }));
}

window.onload = () => {
    bindUnlockAudioOnFirstGesture();

    const somEl = document.getElementById("som-notificacao");
    if (somEl) {
        somEl.checked = isSomNotificacaoAtivo();
        somEl.addEventListener("change", () => setSomNotificacao(somEl.checked));
    }
    const btnMarcarTodas = document.getElementById("btn-marcar-todas-lidas");
    if (btnMarcarTodas) btnMarcarTodas.addEventListener("click", () => marcarTodasComoLidas());
    const inputBuscaContato = document.getElementById("input-busca-contato");
    if (inputBuscaContato) {
        termoBuscaContato = normalizarTextoBusca(inputBuscaContato.value || "");
        inputBuscaContato.addEventListener("input", () => {
            termoBuscaContato = normalizarTextoBusca(inputBuscaContato.value || "");
            renderizarListaContatos();
        });
    }

    carregarContatosNaoLidos().then(() => {
        carregarMensagens(canalAtivo);
    });
    if (canalAtivo === "whatsapp") carregarWahaOverview();
    iniciarPollingMensagens();
    document.querySelectorAll(".canal-btn").forEach((btn) => {
        btn.addEventListener("click", () => setCanalAtivo(btn.getAttribute("data-canal")));
    });
    const primeiroBtn = document.querySelector(".canal-btn[data-canal=\"" + canalAtivo + "\"]");
    if (primeiroBtn) {
        primeiroBtn.classList.add("bg-white", "text-slate-800", "shadow-sm");
        primeiroBtn.classList.remove("text-slate-500");
    }
    const inputMsg = document.getElementById("input-msg");
    if (inputMsg) {
        if (!inputMsgPlaceholderOriginal) {
            inputMsgPlaceholderOriginal = inputMsg.getAttribute("placeholder") || inputMsg.placeholder || "";
        }
        autoResizeInputMsg(inputMsg);
        inputMsg.addEventListener("input", () => {
            autoResizeInputMsg(inputMsg);
        });
        inputMsg.addEventListener("paste", (e) => {
            try {
                if (!e.clipboardData || !e.clipboardData.items) return;
                const items = e.clipboardData.items;
                for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    if (!item || !item.type) continue;
                    const type = String(item.type || "").toLowerCase();
                    if (type.indexOf("image/") === 0) {
                        e.preventDefault();
                        let file = item.getAsFile ? item.getAsFile() : null;
                        if (!file && item.getAsBlob) {
                            const blob = item.getAsBlob();
                            if (blob) file = new File([blob], "clipboard.png", { type: item.type || "image/png" });
                        }
                        if (file) {
                            pendingClipboardFile = file;
                            inputMsg.value = "";
                            inputMsg.setAttribute("placeholder", "Imagem pronta. Toque em enviar.");
                            autoResizeInputMsg(inputMsg);
                        }
                        return;
                    }
                }
            } catch (_) {}
        });
        inputMsg.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                enviarMensagemManual();
            }
            if (e.key === "Enter" && e.shiftKey) {
                // Shift+Enter mantém quebra de linha; ajustamos na próxima frame para evitar flicker.
                requestAnimationFrame(() => autoResizeInputMsg(inputMsg));
            }
        });
    }
    const btnAnexo = document.getElementById("btn-anexo");
    const inputAnexo = document.getElementById("input-anexo");
    if (btnAnexo && inputAnexo) {
        btnAnexo.addEventListener("click", () => inputAnexo.click());
        inputAnexo.addEventListener("change", () => enviarAnexo());
    }
    if (document.getElementById("btn-anexo")) {
        document.getElementById("btn-anexo").style.display = canalAtivo === "whatsapp" ? "" : "none";
    }
    if (document.getElementById("btn-mic")) {
        document.getElementById("btn-mic").style.display = canalAtivo === "whatsapp" ? "" : "none";
    }
    const btnMic = document.getElementById("btn-mic");
    const btnPararAudio = document.getElementById("btn-parar-audio");
    if (btnMic) btnMic.addEventListener("click", () => startRecordingAudio());
    if (btnPararAudio) btnPararAudio.addEventListener("click", () => stopAndSendRecordingAudio());
    const setorSelect = document.getElementById("chat-setor");
    if (setorSelect) {
        setorSelect.addEventListener("change", () => {
            if (!idRemotoAtivo) return;
            const valorAnterior = setorSelect.dataset.lastValue || "";
            const setorId = setorSelect.value ? setorSelect.value.trim() : null;
            const payload = { canal: canalAtivo, remote_id: idRemotoAtivo, setor_id: setorId || null };
            if (typeof window.CHAT_OPERADOR_ID !== "undefined" && window.CHAT_OPERADOR_ID) payload.responsavel_usuario_id = window.CHAT_OPERADOR_ID;
            fetch("/api/conversas/atribuir", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(payload)
            })
                .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
                .then((result) => {
                    if (result.ok) {
                        currentSetorEstado = "atendimento_humano";
                        if (setorSelect.dataset) setorSelect.dataset.lastValue = setorSelect.value;
                        updateIndicadorIA();
                    } else {
                        setorSelect.value = valorAnterior;
                        showPainelToast((result.data && result.data.erro) || "Não foi possível alterar o setor.", "error");
                    }
                })
                .catch(() => { setorSelect.value = valorAnterior; showPainelToast("Erro ao alterar setor. Tente novamente.", "error"); });
        });
    }
    const btnFinalizar = document.getElementById("btn-finalizar-atendimento");
    if (btnFinalizar) {
        btnFinalizar.addEventListener("click", () => {
            if (!idRemotoAtivo) return;
            atualizarSetorNoServidor("atendimento_encerrado");
        });
    }
    const btnAssumir = document.getElementById("btn-assumir-atendimento");
    if (btnAssumir) {
        btnAssumir.addEventListener("click", () => {
            if (!idRemotoAtivo) return;
            const payload = {
                canal: canalAtivo,
                remote_id: idRemotoAtivo,
                setor_id: null
            };
            const respId = typeof window.CHAT_OPERADOR_ID !== "undefined" ? window.CHAT_OPERADOR_ID : null;
            payload.responsavel_usuario_id = respId || null;

            fetch("/api/conversas/atribuir", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(payload)
            })
                .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
                .then((result) => {
                    if (!result.ok) {
                        showPainelToast((result.data && result.data.erro) || "Não foi possível assumir o atendimento.", "error");
                        return;
                    }

                    currentSetorEstado = "atendimento_humano";
                    updateIndicadorIA();

                    const setorSelect = document.getElementById("chat-setor");
                    if (setorSelect) {
                        setorSelect.value = "";
                        if (setorSelect.dataset) setorSelect.dataset.lastValue = "";
                    }

                    // Avisa o cliente que o operador assumiu.
                    const nomeOperador = typeof window.CHAT_ATENDENTE_NOME !== "undefined" ? window.CHAT_ATENDENTE_NOME : "Atendente";
                    const texto = "Assumi seu atendimento agora. Pode contar comigo.";
                    fetch("/api/enviar", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        credentials: "same-origin",
                        body: JSON.stringify({ remote_id: idRemotoAtivo, texto: texto, canal: canalAtivo })
                    }).catch(() => {});
                })
                .catch((e) => {
                    console.warn("[Chat] Erro ao assumir atendimento:", e);
                    showPainelToast("Erro ao assumir atendimento.", "error");
                });
        });
    }
    atualizarBadgesCanais();
};

function atualizarSetorNoServidor(setor) {
    if (!idRemotoAtivo) return;
    fetch("/api/conversacao-setor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remote_id: idRemotoAtivo, setor: setor, canal: canalAtivo })
    })
        .then((r) => r.json())
        .then((d) => {
            if (d.status === "ok") {
                console.log("[Chat] Setor atualizado", d.setor);
                if (setor === "atendimento_encerrado") {
                    currentSetorEstado = "atendimento_ia";
                    const sel = document.getElementById("chat-setor");
                    if (sel) { sel.value = ""; if (sel.dataset) sel.dataset.lastValue = ""; }
                    updateIndicadorIA();
                }
            }
        })
        .catch((e) => console.warn("[Chat] Erro ao atualizar setor", e));
}
