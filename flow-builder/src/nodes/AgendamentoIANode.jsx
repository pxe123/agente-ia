import React, { useCallback, useEffect, useState } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

function serviceIdFromContextExtra(raw) {
  const s = String(raw || '').trim();
  if (!s.startsWith('{')) return '';
  try {
    const j = JSON.parse(s);
    return j && j.service_id != null ? String(j.service_id) : '';
  } catch {
    return '';
  }
}

export function AgendamentoIANode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const label = data?.label ?? 'Agendamento (IA)';
  const notes = data?.notes ?? '';
  const messageTemplate = data?.message_template ?? '';
  const templateOk = data?.template_ok ?? '';
  const templateError = data?.template_error ?? '';
  const contextExtra = data?.context_extra ?? '';
  const showAgendaLink = data?.show_agenda_link !== false && data?.show_agenda_link !== 'false';
  const bookingViaLink = data?.booking_via_link === true || data?.booking_via_link === 'true';

  const [agendaCtx, setAgendaCtx] = useState(null);
  const [agendaErr, setAgendaErr] = useState('');

  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/flow-builder/agenda-context', { credentials: 'same-origin' })
      .then((r) =>
        r.json().then((j) => {
          if (!r.ok) throw new Error((j && j.erro) || `HTTP ${r.status}`);
          return j;
        })
      )
      .then((j) => {
        if (!cancelled) {
          setAgendaCtx(j);
          setAgendaErr('');
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setAgendaCtx(null);
          setAgendaErr(e?.message || 'Falha ao carregar agenda');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!agendaCtx || !Array.isArray(agendaCtx.services) || agendaCtx.services.length !== 1) return;
    const onlyId = agendaCtx.services[0].id;
    if (serviceIdFromContextExtra(contextExtra) === onlyId) return;
    updateNodeData(id, { ...data, context_extra: JSON.stringify({ service_id: onlyId }) });
    scheduleSave();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- aplicar só quando a API devolve um serviço único
  }, [agendaCtx, id]);

  const onLabelChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, label: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onNotesChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, notes: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onMessageTemplateChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, message_template: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onTemplateOkChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, template_ok: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onTemplateErrorChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, template_error: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onShowAgendaLinkChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, show_agenda_link: e.target.checked });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onBookingViaLinkChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, booking_via_link: e.target.checked });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onServicePresetChange = useCallback(
    (e) => {
      const v = (e.target.value || '').trim();
      const nextExtra = v ? JSON.stringify({ service_id: v }) : '';
      updateNodeData(id, { ...data, context_extra: nextExtra });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const sel = serviceIdFromContextExtra(contextExtra);
  const services = Array.isArray(agendaCtx?.services) ? agendaCtx.services : [];
  const selectStyle = {
    width: '100%',
    marginBottom: 8,
    padding: 6,
    borderRadius: 6,
    border: '1px solid rgba(255,255,255,0.2)',
    background: 'rgba(0,0,0,0.25)',
    color: '#fff',
    fontSize: 11,
  };

  return (
    <div
      style={{
        minWidth: 260,
        maxWidth: 340,
        padding: 14,
        background: 'linear-gradient(180deg, #0f766e 0%, #115e59 100%)',
        border: selected ? '2px solid #5eead4' : '1px solid #0d9488',
        borderRadius: 12,
        color: '#ecfdf5',
        fontSize: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
      }}
    >
      <Handle type="target" position={Position.Top} id="in" style={{ top: -4 }} />
      <div
        style={{
          marginBottom: 8,
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          fontWeight: 700,
          color: '#99f6e4',
        }}
      >
        Agendamento IA
      </div>
      <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#ccfbf1', lineHeight: 1.45 }}>
        Usa os dados do questionário/lead (nome, email, telefone). Com “só link”, o ZapAction não chama o motor no
        WhatsApp: envia a mensagem + link e o fluxo segue. Com motor no WhatsApp, o fluxo só avança quando o motor
        devolver <code style={{ fontSize: 9 }}>done: true</code>.
      </p>

      {agendaErr ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#fecaca' }}>{agendaErr}</p>
      ) : null}

      {agendaCtx?.book_page_url ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#a7f3d0', wordBreak: 'break-all', lineHeight: 1.35 }}>
          Página pública:{' '}
          <a href={agendaCtx.book_page_url} target="_blank" rel="noreferrer" style={{ color: '#5eead4' }}>
            {agendaCtx.book_page_url}
          </a>
          <span style={{ display: 'block', marginTop: 4, color: '#99f6e4' }}>
            No WhatsApp o link inclui telefone/nome do contacto quando disponíveis.
          </span>
        </p>
      ) : agendaCtx?.link_generate_available ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#a7f3d0', lineHeight: 1.4 }}>
          Link tokenizado (legado, ~60 min) ao enviar no WhatsApp.
          {agendaCtx.agenda_base_url ? (
            <>
              {' '}
              Base:{' '}
              <span style={{ fontFamily: 'monospace', fontSize: 9 }}>{agendaCtx.agenda_base_url}</span>
            </>
          ) : null}
        </p>
      ) : agendaCtx && !agendaCtx.slug_configured ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#fef08a', lineHeight: 1.4 }}>
          Sem Agenda nem slug: configure <code style={{ fontSize: 9 }}>AGENDAMENTO_IA_BASE_URL</code> ou slug em{' '}
          <a href={agendaCtx.settings_url || '/painel/agenda?tab=clinica'} style={{ color: '#fde047' }}>
            Agenda → Clínica
          </a>
          .
        </p>
      ) : null}

      {!agendaCtx?.link_generate_available && agendaCtx?.slug_configured && agendaCtx.public_url ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#a7f3d0', wordBreak: 'break-all', lineHeight: 1.35 }}>
          Fallback dev:{' '}
          <a href={agendaCtx.public_url} target="_blank" rel="noreferrer" style={{ color: '#5eead4' }}>
            {agendaCtx.public_url}
          </a>
        </p>
      ) : null}

      {agendaCtx && services.length === 0 ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#fef08a' }}>
          Nenhum serviço ativo na agenda. Crie serviços em{' '}
          <a href="/painel/agenda?tab=servicos" style={{ color: '#fde047' }}>
            Agenda → Serviços
          </a>
          .
        </p>
      ) : null}

      {services.length > 1 ? (
        <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>
          Serviço (motor WhatsApp)
        </label>
      ) : null}
      {services.length > 1 ? (
        <select value={sel} onChange={onServicePresetChange} style={selectStyle}>
          <option value="">Cliente escolhe no WhatsApp</option>
          {services.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      ) : null}

      {services.length === 1 ? (
        <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#99f6e4' }}>
          Serviço: <strong>{services[0].name}</strong> (pré-selecionado no motor)
        </p>
      ) : null}

      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontWeight: 600, marginBottom: 8 }}>
        <input type="checkbox" checked={bookingViaLink} onChange={onBookingViaLinkChange} />
        Só enviar link (cliente marca no site; sem horários no WhatsApp)
      </label>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, fontWeight: 600, marginBottom: 8 }}>
        <input type="checkbox" checked={showAgendaLink} onChange={onShowAgendaLinkChange} />
        Incluir link de agendamento (/v1/book/… no Agenda)
      </label>
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Mensagem ao pedir horários (opcional)</label>
      <textarea
        value={messageTemplate}
        onChange={onMessageTemplateChange}
        rows={2}
        placeholder="Em só link: texto curto a enviar com o link. No motor: placeholders {{slot_list}}, …"
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.2)',
          color: '#fff',
          fontSize: 11,
          resize: 'vertical',
        }}
      />
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Mensagem ao concluir (opcional)</label>
      <textarea
        value={templateOk}
        onChange={onTemplateOkChange}
        rows={2}
        placeholder="Vazio = padrão. Ex.: Marcação feita: {{start}} — {{end}}"
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.2)',
          color: '#fff',
          fontSize: 11,
          resize: 'vertical',
        }}
      />
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Mensagem de erro (opcional)</label>
      <textarea
        value={templateError}
        onChange={onTemplateErrorChange}
        rows={2}
        placeholder="Vazio = padrão. Placeholders: {{error_code}}"
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.2)',
          color: '#fff',
          fontSize: 11,
          resize: 'vertical',
        }}
      />
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Rótulo</label>
      <input
        value={label}
        onChange={onLabelChange}
        placeholder="ex.: Marcar consulta"
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.2)',
          color: '#fff',
          fontSize: 12,
        }}
      />
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Notas (interno)</label>
      <textarea
        value={notes}
        onChange={onNotesChange}
        rows={2}
        placeholder="Instruções para a equipa…"
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.2)',
          color: '#fff',
          fontSize: 11,
          resize: 'vertical',
        }}
      />
      <Handle type="source" position={Position.Bottom} id="out" style={{ bottom: -4 }} />
    </div>
  );
}
