import React from 'react';
import { Handle, Position } from '@xyflow/react';

export function StartNode({ selected }) {
  return (
    <div
      style={{
        minWidth: 120,
        padding: '14px 18px',
        background: 'linear-gradient(180deg, #059669 0%, #047857 100%)',
        border: selected ? '2px solid #10b981' : '1px solid #047857',
        borderRadius: 12,
        color: '#fff',
        fontWeight: 700,
        fontSize: 13,
        boxShadow: '0 4px 12px rgba(5, 150, 105, 0.35)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <span style={{ fontSize: 18 }}>▶</span>
      <span>Início</span>
      <Handle type="source" position={Position.Right} id="default" style={{ right: -4 }} />
    </div>
  );
}
