import React, { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

function nowId() {
  return String(Math.random()).slice(2) + String(Date.now());
}

const baseMsgs = [
  { from: "user", text: "Oi! Tem entrega hoje?", channel: "WhatsApp" },
  { from: "bot", text: "Temos sim. Qual bairro e qual item?", channel: "Chatbot" },
  { from: "user", text: "Centro. Quero 2 unidades.", channel: "WhatsApp" },
  { from: "bot", text: "Fecho agora e te envio o link de pagamento. Pode ser?", channel: "Chatbot" },
];

export default function AnimatedChatMock() {
  const reduce = useReducedMotion();
  const [idx, setIdx] = useState(reduce ? baseMsgs.length : 2);

  useEffect(() => {
    if (reduce) return;
    const t1 = setTimeout(() => setIdx(3), 850);
    const t2 = setTimeout(() => setIdx(4), 1750);
    const loop = setInterval(() => setIdx(2), 8000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearInterval(loop);
    };
  }, [reduce]);

  const visible = useMemo(
    () => baseMsgs.slice(0, Math.min(idx, baseMsgs.length)).map((m) => ({ ...m, id: nowId() })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [idx]
  );

  return (
    <div className="glass glow rounded-3xl overflow-hidden">
      <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-sm font-semibold text-white/90">Painel em tempo real</span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-white/60">
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400/80" />
            WhatsApp
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-pink-400/80" />
            Instagram
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-sky-400/80" />
            Messenger
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5">
        <div className="md:col-span-2 border-b md:border-b-0 md:border-r border-white/10 bg-white/[0.02]">
          <div className="p-5">
            <div className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">Fila</div>
            <div className="mt-3 space-y-2.5">
              {[
                { title: "Lead: orçamento", meta: "WhatsApp · 2 min", pill: "Chatbot", pillCls: "bg-emerald-400/15 text-emerald-200" },
                { title: "Dúvida: prazo", meta: "Instagram · agora", pill: "Humano", pillCls: "bg-indigo-400/15 text-indigo-200" },
                { title: "Checkout travou", meta: "Site · 6 min", pill: "Suporte", pillCls: "bg-amber-400/15 text-amber-200" },
              ].map((c) => (
                <div key={c.title} className="ring-soft rounded-2xl bg-white/[0.04] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-white/90 truncate">{c.title}</div>
                      <div className="text-xs text-white/50 truncate">{c.meta}</div>
                    </div>
                    <span className={`text-[10px] font-semibold px-2 py-1 rounded-full ${c.pillCls}`}>{c.pill}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="md:col-span-3">
          <div className="p-5">
            <div className="flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-wider text-white/50 font-semibold">Simulação de chat</div>
              <div className="text-[11px] text-white/40">resposta automática em ~3s</div>
            </div>

            <div className="mt-3 space-y-2.5 min-h-[184px]">
              <AnimatePresence initial={false}>
                {visible.map((m) => {
                  const isUser = m.from === "user";
                  return (
                    <motion.div
                      key={m.id}
                      initial={reduce ? false : { opacity: 0, y: 10, scale: 0.98 }}
                      animate={reduce ? {} : { opacity: 1, y: 0, scale: 1 }}
                      exit={reduce ? {} : { opacity: 0, y: -6, scale: 0.98 }}
                      transition={{ duration: 0.35, ease: "easeOut" }}
                      className={`flex items-end gap-2 ${isUser ? "" : "justify-end"}`}
                    >
                      {isUser && (
                        <div className="w-7 h-7 rounded-full bg-emerald-400/15 text-emerald-200 flex items-center justify-center text-[10px] font-bold">
                          C
                        </div>
                      )}
                      <div
                        className={[
                          "max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-snug",
                          isUser ? "bg-white/[0.06] text-white/85 border border-white/10" : "bg-white text-slate-900",
                        ].join(" ")}
                      >
                        <div className="text-[10px] opacity-70 mb-1">{m.channel}</div>
                        {m.text}
                      </div>
                      {!isUser && (
                        <div className="w-7 h-7 rounded-full bg-white text-slate-900 flex items-center justify-center text-[10px] font-black">
                          BOT
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2.5">
              {[
                { k: "Tempo médio", v: "54s", s: "Chatbot ativo" },
                { k: "Em atendimento", v: "7", s: "2 humanos" },
                { k: "Leads hoje", v: "23", s: "+18%" },
              ].map((x) => (
                <div key={x.k} className="ring-soft rounded-2xl bg-white/[0.04] px-4 py-3">
                  <div className="text-[11px] text-white/50">{x.k}</div>
                  <div className="text-xl font-extrabold text-white/90 mt-0.5">{x.v}</div>
                  <div className="text-[11px] text-white/40 mt-0.5">{x.s}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

