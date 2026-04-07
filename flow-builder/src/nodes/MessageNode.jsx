import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

const MAX_BUTTONS = 3;
const BUTTON_HANDLE_IDS = ['btn_0', 'btn_1', 'btn_2'];

export function MessageNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const text = data?.text ?? '';
  const buttons = Array.isArray(data?.buttons) ? data.buttons : [];
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

  const onButtonTitleChange = useCallback(
    (index, value) => {
      const next = [...buttons];
      if (!next[index]) next[index] = { id: BUTTON_HANDLE_IDS[index], title: '' };
      next[index] = { ...next[index], id: BUTTON_HANDLE_IDS[index], title: value };
      updateNodeData(id, { ...data, buttons: next });
      scheduleSave();
    },
    [id, data, buttons, updateNodeData, scheduleSave]
  );

  const addButton = useCallback(() => {
    if (buttons.length >= MAX_BUTTONS) return;
    const i = buttons.length;
    const next = [...buttons, { id: BUTTON_HANDLE_IDS[i], title: `Opção ${i + 1}` }];
    updateNodeData(id, { ...data, buttons: next });
    scheduleSave();
  }, [id, data, buttons, updateNodeData, scheduleSave]);

  const removeButton = useCallback(
    (index) => {
      const next = buttons
        .filter((_, i) => i !== index)
        .map((b, i) => ({ ...b, id: BUTTON_HANDLE_IDS[i], title: b.title || `Opção ${i + 1}` }));
      updateNodeData(id, { ...data, buttons: next });
      scheduleSave();
    },
    [id, data, buttons, updateNodeData, scheduleSave]
  );

  return (
    <div
      className="react-flow__node-default"
      style={{
        position: 'relative',
        minWidth: 260,
        maxWidth: 360,
        background: '#fff',
        border: selected ? '2px solid #2563eb' : '1px solid #e2e8f0',
        borderRadius: 12,
        padding: 14,
        boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
        overflow: 'visible',
      }}
    >
      <Handle type="target" position={Position.Left} id="target" style={{ left: -4 }} />
      <div style={{ marginBottom: 10, fontWeight: 600, color: '#2563eb', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Mensagem
      </div>
      <p style={{ fontSize: 11, color: '#64748b', margin: '0 0 8px 0', lineHeight: 1.4 }}>
        Cada botão tem uma bolinha (●) à direita: <strong>arraste até o bloco</strong> que deve executar quando a pessoa clicar nesse botão.
      </p>
      <textarea
        value={text}
        onChange={onTextChange}
        placeholder="Digite o texto da mensagem..."
        rows={3}
        style={{
          width: '100%',
          resize: 'vertical',
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          color: '#1e293b',
          padding: 10,
          fontSize: 13,
        }}
      />
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>
          Botões (até {MAX_BUTTONS}) — cada botão tem sua bolinha (●) à direita para conectar ao próximo bloco
        </div>
        {buttons.map((btn, i) => {
          const handleId = (btn.id && String(btn.id).trim()) || BUTTON_HANDLE_IDS[i];
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                marginBottom: 6,
              }}
            >
              <input
                value={btn.title ?? ''}
                onChange={(e) => onButtonTitleChange(i, e.target.value)}
                placeholder={`Texto do botão ${i + 1}`}
                style={{
                  flex: 1,
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  color: '#1e293b',
                  padding: 8,
                  fontSize: 12,
                }}
              />
              <button
                type="button"
                onClick={() => removeButton(i)}
                style={{
                  background: '#f1f5f9',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  color: '#64748b',
                  cursor: 'pointer',
                  padding: '6px 10px',
                  fontSize: 11,
                }}
              >
                Remover
              </button>
              <div
                style={{
                  flexShrink: 0,
                  width: 28,
                  height: 24,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  position: 'relative',
                }}
                title={`Arraste esta bolinha até o bloco que deve rodar para "${(btn.title || '').slice(0, 15)}"`}
              >
                <span style={{ fontSize: 14, color: '#2563eb', marginRight: 2 }}>●</span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={handleId}
                  style={{ right: 0, position: 'relative' }}
                />
              </div>
            </div>
          );
        })}
        {buttons.length < MAX_BUTTONS && (
          <button
            type="button"
            onClick={addButton}
            style={{
              background: 'transparent',
              border: '1px dashed #cbd5e1',
              borderRadius: 8,
              color: '#64748b',
              cursor: 'pointer',
              padding: '8px 10px',
              fontSize: 12,
              width: '100%',
            }}
          >
            + Adicionar botão
          </button>
        )}
      </div>
      {buttons.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
          <span style={{ fontSize: 10, color: '#94a3b8' }}>Saída (sem botões)</span>
          <Handle type="source" position={Position.Right} id="default" style={{ right: -4 }} />
        </div>
      )}
    </div>
  );
}
