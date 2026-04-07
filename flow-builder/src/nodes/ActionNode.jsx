import React, { useCallback, useState, useEffect } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

const ACTION_TYPES = [
  { value: 'transfer_human', label: 'Transferir para humano' },
  { value: 'transfer_to_sector', label: 'Transferir para setor' },
  { value: 'send_link', label: 'Enviar link' },
  { value: 'qualificar_lead', label: 'Qualificar lead' },
];

export function ActionNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const actionType = (data?.actionType || data?.action_type || '').trim() || '';
  // Não usar trim aqui: trim no onChange impede digitar espaço naturalmente.
  const message = (data?.message || data?.messageBeforeTransfer || '');
  const url = (data?.url || '');
  const linkText = (data?.linkText || data?.link_text || '');
  const setorId = (data?.setor_id ?? data?.setorId ?? '').trim();
  const qualifyStatus = (data?.qualifyStatus || data?.status || 'qualificado').trim() || 'qualificado';

  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

  const [setores, setSetores] = useState([]);
  useEffect(() => {
    if (actionType !== 'transfer_to_sector') return;
    fetch('/api/setores', { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : { setores: [] }))
      .then((d) => setSetores(Array.isArray(d?.setores) ? d.setores : []))
      .catch(() => setSetores([]));
  }, [actionType]);

  const onSetorChange = useCallback(
    (e) => {
      const value = (e.target.value || '').trim();
      updateNodeData(id, { ...data, setor_id: value || null, setorId: value || null });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onActionTypeChange = useCallback(
    (e) => {
      const value = (e.target.value || '').trim();
      const next = { ...data, actionType: value, action_type: value };
      // Se o usuário seleciona Qualificar lead mas não mexe no dropdown de status,
      // ainda assim precisamos persistir um status padrão para o backend.
      if (value === 'qualificar_lead') {
        const current = ((data?.qualifyStatus || data?.status) ?? '').toString().trim().toLowerCase();
        const normalized = current === 'desqualificado' ? 'desqualificado' : 'qualificado';
        next.qualifyStatus = normalized;
        next.status = normalized;
      }
      updateNodeData(id, next);
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onMessageChange = useCallback(
    (e) => {
      const raw = (e.target.value ?? '');
      updateNodeData(id, { ...data, message: raw, messageBeforeTransfer: raw });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onMessageBlur = useCallback(
    (e) => {
      const raw = (e.target.value ?? '');
      const trimmed = raw.toString().trim();
      if (trimmed !== raw) updateNodeData(id, { ...data, message: trimmed, messageBeforeTransfer: trimmed });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onUrlChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, url: (e.target.value ?? '') });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onUrlBlur = useCallback(
    (e) => {
      const raw = (e.target.value ?? '');
      const trimmed = raw.toString().trim();
      if (trimmed !== raw) updateNodeData(id, { ...data, url: trimmed });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onLinkTextChange = useCallback(
    (e) => {
      const raw = (e.target.value ?? '');
      updateNodeData(id, { ...data, linkText: raw, link_text: raw });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onLinkTextBlur = useCallback(
    (e) => {
      const raw = (e.target.value ?? '');
      const trimmed = raw.toString().trim();
      if (trimmed !== raw) updateNodeData(id, { ...data, linkText: trimmed, link_text: trimmed });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onQualifyStatusChange = useCallback(
    (e) => {
      const value = (e.target.value || '').trim();
      updateNodeData(id, { ...data, qualifyStatus: value, status: value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  return (
    <div
      style={{
        minWidth: 220,
        maxWidth: 320,
        padding: '12px 16px',
        background: 'linear-gradient(180deg, #78350f 0%, #451a03 100%)',
        border: selected ? '2px solid #f59e0b' : '1px solid #92400e',
        borderRadius: 10,
        color: '#fbbf24',
        fontWeight: 600,
        fontSize: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ left: -4 }} />
      <div style={{ marginBottom: 8, fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#fcd34d' }}>
        Ação
      </div>
      <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
        Tipo de ação
      </label>
      <select
        value={actionType}
        onChange={onActionTypeChange}
        style={{
          width: '100%',
          marginBottom: 10,
          background: '#fff',
          border: '1px solid rgba(251,191,36,0.5)',
          borderRadius: 6,
          color: '#1e293b',
          padding: 8,
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        <option value="" style={{ background: '#fff', color: '#1e293b' }}>Selecione...</option>
        {ACTION_TYPES.map((opt) => (
          <option key={opt.value} value={opt.value} style={{ background: '#fff', color: '#1e293b' }}>
            {opt.label}
          </option>
        ))}
      </select>
      {actionType === 'transfer_human' && (
        <>
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            Mensagem antes de transferir
          </label>
          <input
            type="text"
            value={message}
            onChange={onMessageChange}
            onBlur={onMessageBlur}
            placeholder="Ex.: Um atendente vai te atender."
            style={{
              width: '100%',
              marginBottom: 8,
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid rgba(251,191,36,0.3)',
              borderRadius: 6,
              color: '#fff',
              padding: 8,
              fontSize: 12,
            }}
          />
        </>
      )}
      {actionType === 'transfer_to_sector' && (
        <>
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            Setor de destino
          </label>
          <select
            value={setorId}
            onChange={onSetorChange}
            style={{
              width: '100%',
              marginBottom: 8,
              background: '#fff',
              border: '1px solid rgba(251,191,36,0.5)',
              borderRadius: 6,
              color: '#1e293b',
              padding: 8,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            <option value="" style={{ background: '#fff', color: '#1e293b' }}>Geral</option>
            {setores.filter((s) => s.ativo !== false).map((s) => (
              <option key={s.id} value={s.id || ''} style={{ background: '#fff', color: '#1e293b' }}>
                {s.nome || 'Setor'}
              </option>
            ))}
          </select>
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            Mensagem antes de transferir (opcional)
          </label>
          <input
            type="text"
            value={message}
            onChange={onMessageChange}
            onBlur={onMessageBlur}
            placeholder="Ex.: Encaminhando para o setor de vendas."
            style={{
              width: '100%',
              marginBottom: 8,
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid rgba(251,191,36,0.3)',
              borderRadius: 6,
              color: '#fff',
              padding: 8,
              fontSize: 12,
            }}
          />
        </>
      )}
      {actionType === 'qualificar_lead' && (
        <>
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            Status
          </label>
          <select
            value={qualifyStatus}
            onChange={onQualifyStatusChange}
            style={{
              width: '100%',
              marginBottom: 8,
              background: '#fff',
              border: '1px solid rgba(251,191,36,0.5)',
              borderRadius: 6,
              color: '#1e293b',
              padding: 8,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            <option value="qualificado" style={{ background: '#fff', color: '#1e293b' }}>Qualificado</option>
            <option value="desqualificado" style={{ background: '#fff', color: '#1e293b' }}>Desqualificado</option>
          </select>
        </>
      )}
      {actionType === 'send_link' && (
        <>
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            URL
          </label>
          <input
            type="text"
            value={url}
            onChange={onUrlChange}
            onBlur={onUrlBlur}
            placeholder="https://..."
            style={{
              width: '100%',
              marginBottom: 8,
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid rgba(251,191,36,0.3)',
              borderRadius: 6,
              color: '#fff',
              padding: 8,
              fontSize: 12,
            }}
          />
          <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(251,191,36,0.95)' }}>
            Texto do link (opcional)
          </label>
          <input
            type="text"
            value={linkText}
            onChange={onLinkTextChange}
            onBlur={onLinkTextBlur}
            placeholder="Clique aqui"
            style={{
              width: '100%',
              marginBottom: 8,
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid rgba(251,191,36,0.3)',
              borderRadius: 6,
              color: '#fff',
              padding: 8,
              fontSize: 12,
            }}
          />
        </>
      )}
      <Handle type="source" position={Position.Right} id="default" style={{ right: -4 }} />
    </div>
  );
}
