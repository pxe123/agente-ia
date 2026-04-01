import React from "react";
import { motion, useReducedMotion } from "framer-motion";
import Section from "./components/Section.jsx";
import TiltCard from "./components/TiltCard.jsx";
import AnimatedChatMock from "./components/AnimatedChatMock.jsx";

const ease = [0.22, 1, 0.36, 1];

function TopNav() {
  return (
    <div className="sticky top-0 z-40 border-b border-white/10 bg-[#05070c]/70 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
        <a href="/" className="flex items-center gap-2 font-semibold text-white/90">
          <img src="/static/images/logo.png" alt="ZapAction" className="h-10 w-10 object-contain" />
          <span className="tracking-tight">ZapAction</span>
          <span className="hidden sm:inline text-[11px] px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/60">
            multicanal premium
          </span>
        </a>
        <div className="flex items-center gap-2">
          <a
            href="#como-funciona"
            className="hidden sm:inline-flex px-4 py-2 rounded-2xl text-sm font-semibold text-white/70 hover:text-white hover:bg-white/5 border border-transparent hover:border-white/10 transition"
          >
            Ver como funciona
          </a>
          <a
            href="/cadastro"
            className="inline-flex items-center justify-center px-4 py-2 rounded-2xl text-sm font-semibold text-slate-900 bg-white hover:bg-white/90 transition"
          >
            Testar grátis
          </a>
        </div>
      </div>
    </div>
  );
}

function Hero() {
  const reduce = useReducedMotion();
  return (
    <div className="relative overflow-hidden">
      <div className="bg-animated" aria-hidden="true" />
      <div className="grid-overlay" aria-hidden="true" />
      <div className="noise" aria-hidden="true" />

      <div className="max-w-6xl mx-auto px-4 pt-10 sm:pt-16 pb-10 sm:pb-16 relative">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
          <div className="max-w-xl">
            <motion.div
              initial={reduce ? false : { opacity: 0, y: 14 }}
              animate={reduce ? {} : { opacity: 1, y: 0 }}
              transition={{ duration: 0.8, ease }}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-[12px] text-white/70"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              Atendimento em tempo real + automação com Flow Builder
              <span className="hidden sm:inline text-white/40">•</span>
              <span className="hidden sm:inline text-white/60">WhatsApp-first</span>
            </motion.div>

            <motion.h1
              initial={reduce ? false : { opacity: 0, y: 18 }}
              animate={reduce ? {} : { opacity: 1, y: 0 }}
              transition={{ duration: 0.9, ease, delay: 0.06 }}
              className="mt-6 text-4xl sm:text-6xl font-black tracking-tight text-white"
            >
              Pare de perder vendas por{" "}
              <span className="bg-gradient-to-r from-indigo-300 via-emerald-200 to-pink-200 bg-clip-text text-transparent">
                demora
              </span>{" "}
              no atendimento.
            </motion.h1>

            <motion.p
              initial={reduce ? false : { opacity: 0, y: 16 }}
              animate={reduce ? {} : { opacity: 1, y: 0 }}
              transition={{ duration: 0.85, ease, delay: 0.12 }}
              className="mt-5 text-base sm:text-lg text-white/70 leading-relaxed"
            >
              Centralize WhatsApp, Instagram, Messenger e chat do site em um painel premium. Organize equipe por setores,
              automatize com chatbot e feche mais rápido.
            </motion.p>

            <motion.div
              initial={reduce ? false : { opacity: 0, y: 14 }}
              animate={reduce ? {} : { opacity: 1, y: 0 }}
              transition={{ duration: 0.85, ease, delay: 0.18 }}
              className="mt-8 flex flex-col sm:flex-row gap-3"
            >
              <motion.a
                whileHover={reduce ? {} : { y: -1 }}
                whileTap={reduce ? {} : { scale: 0.98 }}
                href="/cadastro"
                className="btn-primary inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl font-semibold text-slate-950 shadow-[0_18px_70px_rgba(99,102,241,0.28)]"
              >
                Testar grátis
                <motion.span
                  animate={reduce ? {} : { x: [0, 4, 0] }}
                  transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut", repeatDelay: 1.2 }}
                  className="text-slate-950/80"
                >
                  →
                </motion.span>
              </motion.a>
              <motion.a
                whileHover={reduce ? {} : { y: -1 }}
                whileTap={reduce ? {} : { scale: 0.98 }}
                href="#demo"
                className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl font-semibold text-white/85 hover:text-white glass glow-hover transition"
              >
                Ver ao vivo
                <span className="text-white/60">▸</span>
              </motion.a>
            </motion.div>

            <div className="mt-6 flex flex-wrap gap-3 text-[12px] text-white/55">
              <span className="inline-flex items-center gap-2 glass px-3 py-1.5 rounded-2xl">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-300/80" /> Cobrança Mercado Pago
              </span>
              <span className="inline-flex items-center gap-2 glass px-3 py-1.5 rounded-2xl">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-300/80" /> Setup em minutos
              </span>
              <span className="inline-flex items-center gap-2 glass px-3 py-1.5 rounded-2xl">
                <span className="w-1.5 h-1.5 rounded-full bg-pink-300/80" /> Multiatendentes
              </span>
            </div>
          </div>

          <motion.div
            initial={reduce ? false : { opacity: 0, y: 18 }}
            animate={reduce ? {} : { opacity: 1, y: 0 }}
            transition={{ duration: 0.9, ease, delay: 0.12 }}
          >
            <AnimatedChatMock />
            <div className="mt-3 text-center text-xs text-white/40">Mockup animado (simulação).</div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

function FeatureGrid() {
  const features = [
    {
      title: "Multicanal unificado",
      desc: "WhatsApp, Instagram, Messenger e site no mesmo cockpit.",
      accent: "from-indigo-400/30 to-transparent",
    },
    {
      title: "Equipe por setores",
      desc: "Responsáveis, filas e operação organizada para escalar.",
      accent: "from-emerald-400/25 to-transparent",
    },
    {
      title: "Flow Builder + chatbot",
      desc: "Automatize o básico e deixe o humano fechar as vendas.",
      accent: "from-pink-400/25 to-transparent",
    },
    {
      title: "Tempo real",
      desc: "Indicadores, status e mensagens chegando ao vivo.",
      accent: "from-sky-400/25 to-transparent",
    },
    {
      title: "Histórico e contexto",
      desc: "Atenda sem retrabalho e com consistência.",
      accent: "from-violet-400/25 to-transparent",
    },
    {
      title: "Entitlements por plano",
      desc: "Controle de recursos por plano e cobrança recorrente.",
      accent: "from-amber-300/20 to-transparent",
    },
  ];

  return (
    <Section id="features" className="relative py-14 sm:py-20">
      <div className="max-w-6xl mx-auto px-4">
        <div className="max-w-2xl">
          <div className="text-[12px] uppercase tracking-wider text-white/50 font-semibold">Por que parece premium</div>
          <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
            Tecnologia que dá sensação de <span className="text-white/70">controle</span>.
          </h2>
          <p className="mt-3 text-white/65 leading-relaxed">
            Menos caos em canais separados. Mais previsibilidade na operação e mais conversão em vendas.
          </p>
        </div>

        <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {features.map((f) => (
            <TiltCard key={f.title} className="glass glow-hover rounded-3xl p-6 transition">
              <div className={`h-10 w-10 rounded-2xl bg-gradient-to-br ${f.accent} ring-soft`} />
              <div className="mt-4 text-lg font-bold text-white/90">{f.title}</div>
              <div className="mt-2 text-sm text-white/65 leading-relaxed">{f.desc}</div>
              <div className="mt-5 h-px bg-white/10" />
              <div className="mt-4 text-[12px] text-white/45">Microinterações • Glass • Glow • Motion</div>
            </TiltCard>
          ))}
        </div>
      </div>
    </Section>
  );
}

function HowItWorks() {
  const steps = [
    { k: "01", t: "Conecte seus canais", d: "WhatsApp, Instagram, Messenger e chat do site." },
    { k: "02", t: "Desenhe automações", d: "Flow Builder + chatbot para captar e qualificar." },
    { k: "03", t: "Atenda e venda mais", d: "Equipe organizada com histórico e tempo real." },
  ];
  return (
    <Section id="como-funciona" className="relative py-14 sm:py-20">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-end justify-between flex-wrap gap-4">
          <div>
            <div className="text-[12px] uppercase tracking-wider text-white/50 font-semibold">Como funciona</div>
            <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">3 passos. Sem fricção.</h2>
          </div>
          <a href="/cadastro" className="glass rounded-2xl px-4 py-2 text-sm font-semibold text-white/80 hover:text-white hover:bg-white/5 transition">
            Começar agora →
          </a>
        </div>

        <div className="mt-10 grid grid-cols-1 lg:grid-cols-3 gap-4">
          {steps.map((s) => (
            <motion.div
              key={s.k}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className="glass glow-hover rounded-3xl p-6"
            >
              <div className="flex items-center justify-between">
                <div className="text-xs font-black tracking-widest text-white/40">{s.k}</div>
                <div className="w-10 h-10 rounded-2xl bg-white/[0.06] border border-white/10" />
              </div>
              <div className="mt-4 text-lg font-extrabold text-white/90">{s.t}</div>
              <div className="mt-2 text-sm text-white/65">{s.d}</div>
            </motion.div>
          ))}
        </div>
      </div>
    </Section>
  );
}

function Pricing() {
  const plans = [
    { name: "Básico", price: "R$ 97", tag: "Começo rápido", items: ["Multicanal", "Histórico", "1 setor"] },
    { name: "Profissional", price: "R$ 197", tag: "Para vender todo dia", highlight: true, items: ["Equipe (setores)", "Automação", "Dashboard tempo real"] },
    { name: "Avançado", price: "R$ 397", tag: "Escala", items: ["Flow Builder completo", "Mais limites", "Prioridade"] },
  ];
  return (
    <Section id="planos" className="relative py-14 sm:py-20">
      <div className="max-w-6xl mx-auto px-4">
        <div className="text-center max-w-2xl mx-auto">
          <div className="text-[12px] uppercase tracking-wider text-white/50 font-semibold">Planos</div>
          <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">Pronto para virar máquina de vendas?</h2>
          <p className="mt-3 text-white/65">Comece no trial e ative quando estiver pronto.</p>
        </div>

        <div className="mt-10 grid grid-cols-1 lg:grid-cols-3 gap-4">
          {plans.map((p) => (
            <motion.div
              key={p.name}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className={[
                "rounded-3xl p-6 glow-hover",
                p.highlight ? "glass border border-indigo-400/25" : "glass",
              ].join(" ")}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-bold text-white/90">{p.name}</div>
                  <div className="text-[12px] text-white/50 mt-1">{p.tag}</div>
                </div>
                {p.highlight && (
                  <span className="text-[11px] font-semibold px-2 py-1 rounded-full bg-indigo-400/15 text-indigo-200 border border-indigo-300/20">
                    Mais escolhido
                  </span>
                )}
              </div>
              <div className="mt-6 text-4xl font-black text-white">
                {p.price}
                <span className="text-sm font-semibold text-white/45">/mês</span>
              </div>
              <ul className="mt-5 space-y-2 text-sm text-white/70">
                {p.items.map((it) => (
                  <li key={it} className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-300/80" />
                    {it}
                  </li>
                ))}
              </ul>
              <a
                href="/cadastro"
                className={[
                  "mt-7 inline-flex w-full items-center justify-center px-5 py-3.5 rounded-2xl font-semibold transition",
                  p.highlight ? "btn-primary text-slate-950" : "bg-white text-slate-950 hover:bg-white/90",
                ].join(" ")}
              >
                Testar grátis →
              </a>
            </motion.div>
          ))}
        </div>
      </div>
    </Section>
  );
}

function FAQ() {
  const faqs = [
    { q: "Precisa de cartão para testar?", a: "Geralmente não. Você inicia o trial e só ativa a assinatura quando fizer sentido para o seu time." },
    { q: "Funciona com WhatsApp?", a: "Sim. O produto é WhatsApp-first e integra também Instagram, Messenger e chat do site." },
    { q: "Posso cancelar quando quiser?", a: "Sim. Você pode cancelar e interromper a cobrança recorrente." },
    { q: "Tem suporte?", a: "Sim. Suporte para onboarding e melhores práticas de atendimento e automação." },
  ];
  return (
    <Section id="faq" className="relative py-14 sm:py-20">
      <div className="max-w-4xl mx-auto px-4">
        <div className="text-center">
          <div className="text-[12px] uppercase tracking-wider text-white/50 font-semibold">FAQ</div>
          <h2 className="mt-3 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">Sem dúvida. Só decisão.</h2>
        </div>
        <div className="mt-10 space-y-3">
          {faqs.map((x) => (
            <details key={x.q} className="glass rounded-3xl p-6">
              <summary className="cursor-pointer list-none flex items-center justify-between gap-3">
                <span className="font-semibold text-white/90">{x.q}</span>
                <span className="text-white/40">⌄</span>
              </summary>
              <div className="mt-3 text-sm text-white/65 leading-relaxed">{x.a}</div>
            </details>
          ))}
        </div>
      </div>
    </Section>
  );
}

function FinalCTA() {
  return (
    <Section id="demo" className="relative py-14 sm:py-20">
      <div className="max-w-6xl mx-auto px-4">
        <div className="glass glow rounded-3xl p-8 sm:p-10 overflow-hidden relative">
          <div className="absolute -top-24 -left-24 w-96 h-96 bg-gradient-to-br from-indigo-500/25 via-emerald-500/10 to-pink-500/20 blur-3xl" />
          <div className="relative grid grid-cols-1 lg:grid-cols-2 gap-6 items-center">
            <div>
              <div className="text-[12px] uppercase tracking-wider text-white/50 font-semibold">Comece hoje</div>
              <div className="mt-3 text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
                Atendimento premium que <span className="text-white/70">vira venda</span>.
              </div>
              <div className="mt-3 text-white/65">
                Conecte canais, ative automações e veja seu time responder mais rápido — com controle.
              </div>
            </div>
            <div className="flex flex-col sm:flex-row gap-3 lg:justify-end">
              <a href="/cadastro" className="btn-primary inline-flex items-center justify-center px-6 py-3.5 rounded-2xl font-semibold text-slate-950">
                Testar grátis →
              </a>
              <a href="/precos" className="glass inline-flex items-center justify-center px-6 py-3.5 rounded-2xl font-semibold text-white/85 hover:bg-white/5 transition">
                Ver planos
              </a>
            </div>
          </div>
        </div>
        <div className="mt-8 text-center text-xs text-white/35">
          © {new Date().getFullYear()} Up Digital Brasil • Privacidade • Termos
        </div>
      </div>
    </Section>
  );
}

export default function App() {
  return (
    <div>
      <TopNav />
      <Hero />
      <FeatureGrid />
      <HowItWorks />
      <Pricing />
      <FAQ />
      <FinalCTA />
    </div>
  );
}

