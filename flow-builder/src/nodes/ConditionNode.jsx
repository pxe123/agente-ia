import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

const RULE_OPTIONS = [
  { value: 'contém', label: 'Contém' },
  { value: 'igual', label: 'Igual' },
  { value: 'começa com', label: 'Começa com' },
];

export function ConditionNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const rule = (data?.rule || data?.ruleType || '').trim() || '';
  const value = (data?.value || data?.ruleValue || '').trim();
  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

  const onRuleChange = useCallback(
    (e) => {
      const v = (e.target.value || '').trim();
      updateNodeData(id, { ...data, rule: v, ruleType: v });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );
  const onValueChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, value: (e.target.value || '').trim(), ruleValue: (e.target.value || '').trim() });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  return (
    <div
      style={{
        minWidth: 200,
        maxWidth: 280,
        padding: '12px 16px',
        background: 'linear-gradient(180deg, #064e3b 0%, #022c22 100%)',
        border: selected ? '2px solid #10b981' : '1px solid #065f46',
        borderRadius: 10,
        color: '#34d399',
        fontWeight: 600,
        fontSize: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ left: -4 }} />
      <div style={{ marginBottom: 8, fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#6ee7b7' }}>
        Condição
      </div>
      <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(52,211,153,0.95)' }}>
        Tipo de regra
      </label>
      <select
        value={rule}
        onChange={onRuleChange}
        style={{
          width: '100%',
          marginBottom: 8,
          background: 'rgba(0,0,0,0.25)',
          border: '1px solid rgba(52,211,153,0.4)',
          borderRadius: 6,
          color: '#34d399',
          padding: 8,
          fontSize: 12,
        }}
      >
        <option value="">Selecione...</option>
        {RULE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <label style={{ display: 'block', fontSize: 11, marginBottom: 4, color: 'rgba(52,211,153,0.95)' }}>
        Valor (palavra ou frase)
      </label>
      <input
        type="text"
        value={value}
        onChange={onValueChange}
        placeholder="Ex.: preço, ajuda"
        style={{
          width: '100%',
          marginBottom: 8,
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(52,211,153,0.3)',
          borderRadius: 6,
          color: '#fff',
          padding: 8,
          fontSize: 12,
        }}
      />
      <Handle type="source" position={Position.Right} id="sim" style={{ right: -4, top: '30%' }} />
      <Handle type="source" position={Position.Right} id="nao" style={{ right: -4, top: '70%' }} />
    </div>
  );
}
