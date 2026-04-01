import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

const DEFAULT_FIELDS = ['nome', 'email', 'telefone'];

export function LeadNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const fields = Array.isArray(data?.fields) ? data.fields : DEFAULT_FIELDS;

  const onFieldsChange = useCallback(
    (e) => {
      const value = e.target.value;
      const list = value
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      updateNodeData(id, { ...data, fields: list.length ? list : DEFAULT_FIELDS });
    },
    [id, data, updateNodeData]
  );

  const fieldsStr = fields.join(', ');

  return (
    <div
      style={{
        minWidth: 220,
        maxWidth: 320,
        background: 'linear-gradient(180deg, #0e7490 0%, #155e75 100%)',
        border: selected ? '2px solid #22d3ee' : '1px solid #0e7490',
        borderRadius: 12,
        padding: 14,
        color: '#fff',
        boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ left: -4 }} />
      <div style={{ marginBottom: 8, fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#a5f3fc' }}>
        Salvar lead
      </div>
      <p style={{ fontSize: 11, margin: '0 0 8px 0', opacity: 0.95 }}>
        Salva os dados coletados no fluxo (ex.: questionário) na base de leads. Use depois do questionário ou de mensagens que capturam dados.
      </p>
      <label style={{ display: 'block', fontSize: 11, marginBottom: 4 }}>
        Campos a salvar (separados por vírgula):
      </label>
      <input
        type="text"
        value={fieldsStr}
        onChange={onFieldsChange}
        placeholder="nome, email, telefone"
        style={{
          width: '100%',
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(255,255,255,0.3)',
          borderRadius: 6,
          color: '#fff',
          padding: 8,
          fontSize: 12,
        }}
      />
      <Handle type="source" position={Position.Right} id="default" style={{ right: -4 }} />
    </div>
  );
}
