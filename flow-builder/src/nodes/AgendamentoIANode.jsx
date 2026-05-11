import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

export function AgendamentoIANode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const label = data?.label ?? 'Agendamento (IA)';
  const notes = data?.notes ?? '';
  const contextExtra = data?.context_extra ?? '';
  const messageTemplate = data?.message_template ?? '';
  const messageTemplates = data?.message_templates ?? '';

  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

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

  const onContextExtraChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, context_extra: e.target.value });
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

  const onMessageTemplatesChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, message_templates: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  return (
    <div
      style={{
        minWidth: 240,
        maxWidth: 320,
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
      <p style={{ margin: '0 0 8px 0', fontSize: 10, color: '#ccfbf1', lineHeight: 1.4 }}>
        API devolve só dados (sem mensagem do servidor). O texto no WhatsApp vem dos templates abaixo. Ao concluir (
        <code style={{ fontSize: 9 }}>done: true</code>
        ), o fluxo avança para a aresta.
      </p>
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Mensagem por defeito</label>
      <textarea
        value={messageTemplate}
        onChange={onMessageTemplateChange}
        rows={2}
        placeholder='ex.: "Horários: {{slot_list}}"'
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
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>message_templates (JSON)</label>
      <textarea
        value={messageTemplates}
        onChange={onMessageTemplatesChange}
        rows={5}
        placeholder='{ "default": "…", "needs_input": "…", "ok": "…", "error": "…" }'
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          marginBottom: 8,
          fontFamily: 'ui-monospace, Consolas, monospace',
          fontSize: 9,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.3)',
          color: '#f0fdfa',
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
        placeholder="Instruções para a equipa / lembrete…"
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
      <label style={{ display: 'block', fontSize: 10, fontWeight: 600, marginBottom: 4 }}>Contexto extra (JSON opcional)</label>
      <textarea
        value={contextExtra}
        onChange={onContextExtraChange}
        rows={3}
        placeholder='ex.: { "service_id": "42" }'
        autoComplete="off"
        spellCheck={false}
        style={{
          width: '100%',
          fontFamily: 'ui-monospace, Consolas, monospace',
          fontSize: 10,
          padding: 6,
          borderRadius: 6,
          border: '1px solid rgba(255,255,255,0.2)',
          background: 'rgba(0,0,0,0.25)',
          color: '#ecfeff',
          resize: 'vertical',
        }}
      />
      <Handle type="source" position={Position.Bottom} id="out" style={{ bottom: -4 }} />
    </div>
  );
}
