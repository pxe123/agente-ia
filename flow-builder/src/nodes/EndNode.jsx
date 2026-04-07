import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

export function EndNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const text = data?.text ?? '';
  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

  const onTextChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, text: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  return (
    <div
      style={{
        minWidth: 200,
        padding: 14,
        background: 'linear-gradient(180deg, #7f1d1d 0%, #450a0a 100%)',
        border: selected ? '2px solid #f87171' : '1px solid #991b1b',
        borderRadius: 12,
        color: '#fecaca',
        fontWeight: 600,
        fontSize: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ left: -4 }} />
      <div style={{ marginBottom: 8, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Finalizar
      </div>
      <textarea
        value={text}
        onChange={onTextChange}
        placeholder="Mensagem de despedida (opcional)"
        rows={2}
        style={{
          width: '100%',
          resize: 'vertical',
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(254,202,202,0.3)',
          borderRadius: 6,
          color: '#fff',
          padding: 8,
          fontSize: 12,
        }}
      />
    </div>
  );
}
