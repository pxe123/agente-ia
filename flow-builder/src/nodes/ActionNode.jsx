import React, { useCallback, useState, useEffect } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

// #region agent log helpers
const DEBUG_LOG_INGEST = 'http://127.0.0.1:7868/ingest/c5c23a0e-51b5-4bd5-bcc2-994f3e027bbc';
const DEBUG_SESSION_ID = '1db042';
function agentDebugLog(payload) {
  return fetch(DEBUG_LOG_INGEST, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': DEBUG_SESSION_ID },
    body: JSON.stringify({ ...payload, sessionId: DEBUG_SESSION_ID, timestamp: payload.timestamp ?? Date.now() }),
  }).catch(() => {});
}
// #endregion

const ACTION_TYPES = [
  { value: 'transfer_human', label: 'Transferir para humano' },
  { value: 'transfer_to_sector', label: 'Transferir para setor' },
  { value: 'send_link', label: 'Enviar link' },
  { value: 'qualificar_lead', label: 'Qualificar lead' },
];

export function ActionNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const actionType = (data?.actionType || data?.action_type || '').trim() || '';
  const message = (data?.message || data?.messageBeforeTransfer || '').trim();
  const url = (data?.url || '').trim();
  const linkText = (data?.linkText || data?.link_text || '').trim();
  const setorId = (data?.setor_id ?? data?.setorId ?? '').trim();
  const qualifyStatus = (data?.qualifyStatus || data?.status || 'qualificado').trim() || 'qualificado';

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
    },
    [id, data, updateNodeData]
  );

  const onActionTypeChange = useCallback(
    (e) => {
      const value = (e.target.value || '').trim();
      updateNodeData(id, { ...data, actionType: value, action_type: value });
    },
    [id, data, updateNodeData]
  );
  const onMessageChange = useCallback(
    (e) => {
      const raw = (e.target.value || '');
      const trimmed = raw.trim();
      // #region agent log action_message_change_trim
      agentDebugLog({
        runId: 'pre-debug',
        hypothesisId: 'H1_trim_removes_trailing_space_on_each_keystroke',
        location: 'flow-builder/src/nodes/ActionNode.jsx:onMessageChange',
        message: 'action message input change',
        data: {
          actionType,
          raw_len: raw.length,
          trimmed_len: trimmed.length,
          raw_ends_with_space: raw.endsWith(' '),
          trimmed_ends_with_space: trimmed.endsWith(' '),
          raw_last_char: raw ? raw.slice(-1) : '',
        },
      });
      // #endregion
      const value = trimmed;
      updateNodeData(id, { ...data, message: value, messageBeforeTransfer: value });
    },
    [id, data, updateNodeData]
  );
  const onUrlChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, url: (e.target.value || '').trim() });
    },
    [id, data, updateNodeData]
  );
  const onLinkTextChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, linkText: (e.target.value || '').trim(), link_text: (e.target.value || '').trim() });
    },
    [id, data, updateNodeData]
  );
  const onQualifyStatusChange = useCallback(
    (e) => {
      const value = (e.target.value || '').trim();
      updateNodeData(id, { ...data, qualifyStatus: value, status: value });
    },
    [id, data, updateNodeData]
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
            onKeyDown={(e) => {
              if (e.key !== ' ') return;
              // #region agent log action_message_keydown_space
              agentDebugLog({
                runId: 'pre-debug',
                hypothesisId: 'H1_trim_removes_trailing_space_on_each_keystroke',
                location: 'flow-builder/src/nodes/ActionNode.jsx:onKeyDown',
                message: 'space keydown on action message',
                data: {
                  actionType,
                  current_value_ends_with_space: String(e.currentTarget.value || '').endsWith(' '),
                  current_value: String(e.currentTarget.value || ''),
                },
              });
              // #endregion
            }}
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
