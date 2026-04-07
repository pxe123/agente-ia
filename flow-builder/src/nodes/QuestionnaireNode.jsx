import React, { useCallback } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';

const KEY_OPTIONS = [
  { value: 'nome', label: 'Nome' },
  { value: 'email', label: 'E-mail' },
  { value: 'telefone', label: 'Telefone' },
  { value: '_outro', label: 'Outro (digite abaixo)' },
];
const PREDEFINED_KEYS = ['nome', 'email', 'telefone'];

export function QuestionnaireNode({ data, id, selected }) {
  const { updateNodeData } = useReactFlow();
  const intro = data?.intro ?? '';
  const questions = Array.isArray(data?.questions) ? data.questions : [];
  const questionKeys = Array.isArray(data?.questionKeys) ? data.questionKeys : [];
  const keys = questions.map((_, i) => questionKeys[i] ?? (questions[i] ? 'campo_' + (i + 1) : ''));
  const scheduleSave = useCallback(() => {
    try {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('flowbuilder:scheduleSave'));
    } catch (_) {}
  }, []);

  const onIntroChange = useCallback(
    (e) => {
      updateNodeData(id, { ...data, intro: e.target.value });
      scheduleSave();
    },
    [id, data, updateNodeData, scheduleSave]
  );

  const onQuestionChange = useCallback(
    (index, value) => {
      const next = [...questions];
      next[index] = value;
      updateNodeData(id, { ...data, questions: next });
      scheduleSave();
    },
    [id, data, questions, updateNodeData, scheduleSave]
  );

  const onKeyChange = useCallback(
    (index, value) => {
      const next = [...questionKeys];
      while (next.length <= index) next.push('');
      next[index] = (value || '').trim().toLowerCase();
      updateNodeData(id, { ...data, questionKeys: next });
      scheduleSave();
    },
    [id, data, questionKeys, updateNodeData, scheduleSave]
  );

  const addQuestion = useCallback(() => {
    const nextKeys = [...questionKeys];
    while (nextKeys.length < questions.length + 1) nextKeys.push('');
    nextKeys[questions.length] = nextKeys[questions.length] || 'campo_' + (questions.length + 1);
    updateNodeData(id, { ...data, questions: [...questions, ''], questionKeys: nextKeys });
    scheduleSave();
  }, [id, data, questions, questionKeys, updateNodeData, scheduleSave]);

  const removeQuestion = useCallback(
    (index) => {
      const nextQ = questions.filter((_, i) => i !== index);
      const nextK = questionKeys.filter((_, i) => i !== index);
      updateNodeData(id, { ...data, questions: nextQ, questionKeys: nextK });
      scheduleSave();
    },
    [id, data, questions, questionKeys, updateNodeData, scheduleSave]
  );

  return (
    <div
      style={{
        minWidth: 260,
        maxWidth: 380,
        background: '#fff',
        border: selected ? '2px solid #7c3aed' : '1px solid #e2e8f0',
        borderRadius: 12,
        padding: 14,
        boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ left: -4 }} />
      <div style={{ marginBottom: 10, fontWeight: 600, color: '#7c3aed', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Questionário
      </div>
      <input
        value={intro}
        onChange={onIntroChange}
        placeholder="Texto introdutório (opcional)"
        style={{
          width: '100%',
          marginBottom: 10,
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          color: '#1e293b',
          padding: 8,
          fontSize: 12,
        }}
      />
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6 }}>Perguntas e chave para Salvar lead (nome, email, telefone):</div>
      {questions.map((q, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
            <span style={{ color: '#64748b', fontSize: 12, flexShrink: 0 }}>{i + 1}.</span>
            <input
              value={q}
              onChange={(e) => onQuestionChange(i, e.target.value)}
              placeholder={`Pergunta ${i + 1}`}
              style={{
                flex: 1,
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
                color: '#1e293b',
                padding: 6,
                fontSize: 12,
              }}
            />
            <button
              type="button"
              onClick={() => removeQuestion(i)}
              style={{
                background: '#f1f5f9',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
                color: '#64748b',
                cursor: 'pointer',
                padding: '4px 8px',
                fontSize: 11,
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 20 }}>
            <span style={{ color: '#94a3b8', fontSize: 11 }}>Chave:</span>
            <select
              value={PREDEFINED_KEYS.includes(keys[i]) ? keys[i] : '_outro'}
              onChange={(e) => {
                const v = e.target.value;
                onKeyChange(i, v === '_outro' ? (keys[i] && !PREDEFINED_KEYS.includes(keys[i]) ? keys[i] : '') : v);
              }}
              style={{
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: 6,
                color: '#1e293b',
                padding: 4,
                fontSize: 11,
                minWidth: 120,
              }}
            >
              {KEY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {!PREDEFINED_KEYS.includes(keys[i]) && (
              <input
                value={keys[i] || ''}
                onChange={(e) => onKeyChange(i, e.target.value)}
                placeholder="ex: empresa, cargo"
                style={{
                  width: 90,
                  background: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: 6,
                  color: '#1e293b',
                  padding: 4,
                  fontSize: 11,
                }}
              />
            )}
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={addQuestion}
        style={{
          background: 'transparent',
          border: '1px dashed #c4b5fd',
          borderRadius: 8,
          color: '#7c3aed',
          cursor: 'pointer',
          padding: '8px 10px',
          fontSize: 12,
          width: '100%',
        }}
      >
        + Adicionar pergunta
      </button>
      <Handle type="source" position={Position.Right} id="default" style={{ right: -4 }} />
    </div>
  );
}
