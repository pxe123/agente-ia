import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  Panel,
} from '@xyflow/react';
import { MessageNode } from './nodes/MessageNode';
import { ConditionNode } from './nodes/ConditionNode';
import { ActionNode } from './nodes/ActionNode';
import { StartNode } from './nodes/StartNode';
import { EndNode } from './nodes/EndNode';
import { QuestionnaireNode } from './nodes/QuestionnaireNode';
import { LeadNode } from './nodes/LeadNode';
import { fetchFlowsList, fetchFlowJson, saveFlowJson, getCsrfToken } from './api/flows';

// Tipos de nó do canvas; "message" = nó de mensagem com botões (cada botão tem Handle próprio)
const nodeTypes = {
  message: MessageNode,
  condition: ConditionNode,
  action: ActionNode,
  start: StartNode,
  end: EndNode,
  questionnaire: QuestionnaireNode,
  lead: LeadNode,
};

const DEBOUNCE_SAVE_MS = 3000;

function getChatbotIdFromUrl() {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  return params.get('chatbot_id') || null;
}

function flowValidationErrors(nodes, edges) {
  const nodeIds = new Set(nodes.map((n) => n.id));
  const connected = new Set();
  edges.forEach((e) => {
    connected.add(e.source);
    connected.add(e.target);
  });
  return [...nodeIds].filter((id) => !connected.has(id));
}

function FlowBuilderInner() {
  const [chatbotId] = useState(() => getChatbotIdFromUrl());
  const [flowsList, setFlowsList] = useState([]);
  const [currentChannel, setCurrentChannel] = useState('default');
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [flowName, setFlowName] = useState('');
  const [saveStatus, setSaveStatus] = useState('');
  const [validationError, setValidationError] = useState('');
  const saveTimeoutRef = useRef(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const reactFlowInstanceRef = useRef(null);
  const canvasInnerRef = useRef(null);
  useEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, [nodes, edges]);

  const hasSelection = nodes.some((n) => n.selected) || edges.some((e) => e.selected);

  // Quando há nós no canvas, ajustar a view para que todos fiquem visíveis (container precisa de altura antes)
  const fitViewToNodes = useCallback(() => {
    try {
      reactFlowInstanceRef.current?.fitView?.({ padding: 0.25, duration: 200 });
    } catch (_) {}
  }, []);
  useEffect(() => {
    if (nodes.length === 0 || !reactFlowInstanceRef.current) return;
    const t1 = setTimeout(fitViewToNodes, 100);
    const t2 = setTimeout(fitViewToNodes, 500);
    const t3 = setTimeout(fitViewToNodes, 1200);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [nodes.length, currentChannel, fitViewToNodes]);

  const loadFlowsList = useCallback(async () => {
    try {
      const data = await fetchFlowsList();
      if (data.flows) setFlowsList(data.flows);
    } catch (e) {
      setSaveStatus('Erro ao carregar lista.');
    }
  }, []);

  const loadFlow = useCallback(
    async (channel) => {
      const ch = channel || currentChannel;
      const cid = chatbotId;
      try {
        const data = await fetchFlowJson({ chatbotId: cid, channel: ch });
        if (data.flow_json?.nodes?.length) {
          const rawNodes = data.flow_json.nodes;
          const BUTTON_HANDLES = ['btn_0', 'btn_1', 'btn_2'];
          const nodesWithPosition = rawNodes.map((n, i) => {
            const pos = n.position || {};
            const num = (v) => (typeof v === 'number' && !Number.isNaN(v) ? v : null);
            const x = num(pos.x) ?? 100 + (i % 2) * 300;
            const y = num(pos.y) ?? 100 + Math.floor(i / 2) * 160;
            let nodeData = n.data != null ? n.data : {};
            if (n.type === 'message' && Array.isArray(nodeData.buttons)) {
              nodeData = {
                ...nodeData,
                buttons: nodeData.buttons.slice(0, 3).map((b, j) => ({
                  ...(typeof b === 'object' && b ? b : {}),
                  id: BUTTON_HANDLES[j],
                  title: (typeof b === 'object' && b && (b.title || b.label)) ? (b.title || b.label) : `Opção ${j + 1}`,
                })),
              };
            }
            return {
              id: n.id,
              type: (n.type && ['message', 'condition', 'action', 'start', 'end', 'questionnaire', 'lead'].includes(n.type)) ? n.type : 'message',
              position: { x, y },
              data: nodeData,
            };
          });
          let edges = data.flow_json.edges || [];
          nodesWithPosition.forEach((node) => {
            if (node.type !== 'message' || !Array.isArray(node.data?.buttons)) return;
            const handleMap = {};
            node.data.buttons.forEach((b, j) => {
              const h = BUTTON_HANDLES[j];
              if (!h) return;
              handleMap[h] = h;
              const oldId = (b.id || '').toString().trim();
              const title = (b.title || b.label || '').toString().trim().toLowerCase();
              if (oldId && oldId !== h) handleMap[oldId] = h;
              if (title) handleMap[title] = h;
            });
            edges = edges.map((e) => {
              if (e.source !== node.id || !e.sourceHandle) return e;
              const newHandle = handleMap[e.sourceHandle];
              return newHandle ? { ...e, sourceHandle: newHandle } : e;
            });
          });
          setNodes(nodesWithPosition);
          setEdges(edges);
        } else {
          setNodes([]);
          setEdges([]);
        }
        setFlowName(data.name || data.label || ch);
        setCurrentChannel(ch);
      } catch (e) {
        setSaveStatus('Erro ao carregar fluxo.');
      }
    },
    [currentChannel, chatbotId, setNodes, setEdges]
  );

  useEffect(() => {
    if (!chatbotId) loadFlowsList();
  }, [chatbotId, loadFlowsList]);

  useEffect(() => {
    if (chatbotId) {
      loadFlow(null);
    } else {
      loadFlow('default');
    }
  }, [chatbotId]);

  const selectFlow = useCallback(
    (channel) => {
      setCurrentChannel(channel);
      loadFlow(channel);
    },
    [loadFlow]
  );

  const saveFlow = useCallback(
    async (nodesToSave, edgesToSave) => {
      const soltos = flowValidationErrors(nodesToSave, edgesToSave);
      if (soltos.length > 0) {
        setValidationError(
          `Alguns blocos não estão conectados. Arraste da bolinha (●) de um bloco até a bolinha de outro para ligar. Desconectados: ${soltos.join(', ')}`
        );
      } else {
        setValidationError('');
      }
      setSaveStatus('Salvando...');
      // Payload aceito pelo backend: channel OU chatbot_id, name, flow_json (objeto, não string)
      const flow_json = {
        nodes: nodesToSave.map(({ id, type, data, position }) => ({
          id,
          type: type || 'message',
          data: data || {},
          position: position || { x: 0, y: 0 },
        })),
        edges: edgesToSave.map(({ id, source, target, sourceHandle }) => {
          const edge = { id: id || `${source}-${target}-${sourceHandle || 'default'}`, source, target };
          if (sourceHandle != null && sourceHandle !== '') edge.sourceHandle = sourceHandle;
          return edge;
        }),
      };
      const payload = {
        ...(chatbotId ? { chatbot_id: chatbotId } : { channel: currentChannel }),
        name: flowName,
        flow_json,
      };
      try {
        const { response, json } = await saveFlowJson(payload);
        const res = json || {};
        if (response.ok && res.ok) {
          if (res.aviso) setValidationError(res.aviso);
          setSaveStatus(soltos.length > 0 ? 'Salvo. Conecte os blocos para o fluxo funcionar.' : 'Salvo.');
          setTimeout(() => setSaveStatus(''), 4000);
          loadFlowsList();
        } else {
          const msg = res.error || res.erro || 'Erro ao salvar.';
          setValidationError(msg);
          setSaveStatus(msg);
        }
      } catch (e) {
        setSaveStatus('Erro de conexão.');
      }
    },
    [currentChannel, flowName, chatbotId, loadFlowsList]
  );

  const scheduleSave = useCallback(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      saveFlow(nodesRef.current, edgesRef.current);
      saveTimeoutRef.current = null;
    }, DEBOUNCE_SAVE_MS);
  }, [saveFlow]);

  // Alguns updates de formulário (updateNodeData dentro dos nós) não passam por onNodesChange.
  // Escutamos um evento simples para disparar o autosave sempre que o usuário editar dados.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handler = () => scheduleSave();
    window.addEventListener('flowbuilder:scheduleSave', handler);
    return () => window.removeEventListener('flowbuilder:scheduleSave', handler);
  }, [scheduleSave]);

  const onConnect = useCallback((params) => {
    setEdges((eds) => addEdge(params, eds));
    scheduleSave();
  }, [setEdges, scheduleSave]);

  const onNodesChangeLocal = useCallback(
    (changes) => {
      onNodesChange(changes);
      scheduleSave();
    },
    [onNodesChange, scheduleSave]
  );

  const onEdgesChangeLocal = useCallback(
    (changes) => {
      onEdgesChange(changes);
      scheduleSave();
    },
    [onEdgesChange, scheduleSave]
  );

  const removeSelected = useCallback(() => {
    const selectedNodeIds = new Set((nodesRef.current || []).filter((n) => n?.selected).map((n) => n.id));
    const selectedEdgeIds = new Set((edgesRef.current || []).filter((e) => e?.selected).map((e) => e.id));
    if (selectedNodeIds.size === 0 && selectedEdgeIds.size === 0) return;

    setNodes((nds) => nds.filter((n) => !selectedNodeIds.has(n.id)));
    setEdges((eds) =>
      eds.filter(
        (e) => !selectedEdgeIds.has(e.id) && !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target)
      )
    );
    scheduleSave();
  }, [setNodes, setEdges, scheduleSave]);

  const clearFlow = useCallback(() => {
    const ok = window.confirm('Tem certeza que deseja apagar todos os blocos e conexões deste fluxo?');
    if (!ok) return;
    setNodes([]);
    setEdges([]);
    scheduleSave();
  }, [setNodes, setEdges, scheduleSave]);

  const deleteAllFlowsInDb = useCallback(async () => {
    const ok = window.confirm(
      'Apagar TODOS os fluxos salvos no banco? O chatbot deixará de usar fluxos antigos. Depois clique em Salvar para gravar só o fluxo do canvas.'
    );
    if (!ok) return;
    setSaveStatus('Apagando fluxos no banco...');
    try {
      const token = await getCsrfToken();
      const r = await fetch('/api/flows/delete-all', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      });
      const data = await r.json();
      if (data && data.ok) {
        setSaveStatus('Todos os fluxos apagados no banco. Clique em Salvar para gravar só este fluxo.');
        setTimeout(() => setSaveStatus(''), 6000);
      } else {
        setSaveStatus(data?.erro ? `Erro: ${data.erro}` : 'Erro ao apagar fluxos.');
      }
    } catch {
      setSaveStatus('Erro de conexão ao apagar fluxos.');
    }
  }, []);

  // Teclas Delete/Backspace apagam seleção (sem interferir ao digitar em inputs)
  useEffect(() => {
    const onKeyDown = (e) => {
      const key = e.key;
      if (key !== 'Delete' && key !== 'Backspace') return;
      const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
      if (tag === 'input' || tag === 'textarea' || e.target?.isContentEditable) return;
      e.preventDefault();
      removeSelected();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [removeSelected]);

  const addNode = useCallback(
    (type = 'message') => {
      const id = `${type}_${Date.now()}`;
      const defaults = {
        message: { text: '', buttons: [] },
        condition: { label: 'Condição', rule: '', value: '' },
        action: { label: 'Ação', actionType: '', message: '', url: '', linkText: '', qualifyStatus: 'qualificado', status: 'qualificado' },
        start: {},
        end: { text: '' },
        questionnaire: { intro: '', questions: [] },
        lead: { fields: ['nome', 'email', 'telefone'] },
      };

      const instance = reactFlowInstanceRef.current;
      const canvasEl = canvasInnerRef.current;
      let pos = null;
      try {
        if (instance && canvasEl && typeof canvasEl.getBoundingClientRect === 'function') {
          const r = canvasEl.getBoundingClientRect();
          const screen = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
          if (typeof instance.screenToFlowPosition === 'function') {
            pos = instance.screenToFlowPosition(screen);
          } else if (typeof instance.project === 'function') {
            pos = instance.project(screen);
          }
        }
      } catch (_) {
        pos = null;
      }

      setNodes((nds) => {
        const count = nds.length;
        const fallbackX = 100 + (count % 2) * 300;
        const fallbackY = 100 + Math.floor(count / 2) * 160;
        const baseX = (pos && typeof pos.x === 'number') ? pos.x : fallbackX;
        const baseY = (pos && typeof pos.y === 'number') ? pos.y : fallbackY;
        // Leve offset para não “nascer em cima” do nó anterior quando o usuário adiciona vários seguidos.
        const x = baseX + (count % 3) * 24;
        const y = baseY + (count % 3) * 24;
        const newNode = {
          id,
          type,
          position: { x, y },
          data: defaults[type] ?? {},
        };
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try {
              // Garante que o novo nó apareça dentro da visualização do usuário.
              const rf = reactFlowInstanceRef.current;
              if (rf && typeof rf.setCenter === 'function') {
                const z = typeof rf.getZoom === 'function' ? rf.getZoom() : undefined;
                rf.setCenter(x, y, { zoom: z, duration: 200 });
              } else {
                rf?.fitView?.({ padding: 0.3, duration: 200 });
              }
            } catch (_) {}
          });
        });
        return [...nds, newNode];
      });
      scheduleSave();
    },
    [setNodes, scheduleSave]
  );

  const currentFlowMeta = flowsList.find((f) => f.channel === currentChannel);
  const isEmbedded = typeof window !== 'undefined' && window.self !== window.top;
  const isChatbotMode = Boolean(chatbotId);

  return (
    <div className={`flow-app ${isEmbedded ? 'flow-app--embedded' : ''} ${isChatbotMode ? 'flow-app--chatbot' : ''}`}>
      {/* Sidebar: oculta em modo chatbot (acesso por Meus Chatbots) */}
      {!isChatbotMode && (
      <aside className="flow-sidebar">
        {!isEmbedded && (
          <a href="/" className="flow-sidebar-back">
            ← Voltar ao painel
          </a>
        )}
        <h2 className="flow-sidebar-title">Flow Builder</h2>
        <p className="flow-sidebar-sub">Escolha para qual canal ou gatilho configurar o chatbot:</p>

        <div className="flow-sidebar-list">
          {(flowsList.length ? flowsList : [{ channel: 'default', label: 'Resposta padrão', description: '' }]).map((f) => (
            <button
              key={f.channel}
              type="button"
              className={`flow-sidebar-item ${currentChannel === f.channel ? 'flow-sidebar-item--active' : ''}`}
              onClick={() => selectFlow(f.channel)}
            >
              <span className="flow-sidebar-item-label">
                <span className="flow-sidebar-item-dot" />
                {f.label}
              </span>
              {f.description && <span className="flow-sidebar-item-desc">{f.description}</span>}
            </button>
          ))}
        </div>

        <div className="flow-sidebar-blocks">
          <div className="flow-sidebar-blocks-title">Blocos do fluxo</div>
          <p className="flow-sidebar-blocks-sub">Clique para adicionar ao diagrama:</p>
          <div className="flow-sidebar-blocks-grid">
            <button type="button" onClick={() => addNode('start')} className="flow-block-btn flow-block-btn--start" title="Ponto de entrada do fluxo">
              Início
            </button>
            <button type="button" onClick={() => addNode('message')} className="flow-block-btn flow-block-btn--message" title="Enviar mensagem com texto e botões">
              Mensagem
            </button>
            <button type="button" onClick={() => addNode('questionnaire')} className="flow-block-btn flow-block-btn--questionnaire" title="Lista de perguntas em uma mensagem">
              Questionário
            </button>
            <button type="button" onClick={() => addNode('condition')} className="flow-block-btn flow-block-btn--condition" title="Desvio Sim/Não">
              Condição
            </button>
            <button type="button" onClick={() => addNode('lead')} className="flow-block-btn flow-block-btn--lead" title="Salvar dados como lead no banco">
              Salvar lead
            </button>
            <button type="button" onClick={() => addNode('action')} className="flow-block-btn flow-block-btn--action" title="Ação customizada">
              Ação
            </button>
            <button type="button" onClick={() => addNode('end')} className="flow-block-btn flow-block-btn--end" title="Encerrar conversa">
              Finalizar
            </button>
          </div>
        </div>

        <div className="flow-sidebar-footer">
          <span className="flow-sidebar-hint">Arraste da bolinha (●) de um bloco até a bolinha de outro para conectar e definir o caminho da conversa.</span>
        </div>
      </aside>
      )}

      {/* Área principal: header + canvas */}
      <main className="flow-main">
        <header className="flow-header">
          <div className="flow-header-left">
            <h1 className="flow-header-title">{flowName || currentFlowMeta?.label || currentChannel}</h1>
            {currentFlowMeta?.description && (
              <span className="flow-header-desc">{currentFlowMeta.description}</span>
            )}
          </div>
          <div className="flow-header-right">
            {validationError && <span className="flow-header-error">{validationError}</span>}
            {saveStatus && (
              <span className={saveStatus.startsWith('Erro') || saveStatus.includes('Não salvo') ? 'flow-header-error' : 'flow-header-ok'}>
                {saveStatus}
              </span>
            )}
          </div>
        </header>

        <div className="flow-canvas-wrap" role="region" aria-label="Área do diagrama">
          <div
            className="flow-canvas-inner"
            ref={canvasInnerRef}
            style={
              isChatbotMode
                ? { width: '100%', height: '100%', minHeight: 280 }
                : { width: '100%', height: 520, minHeight: 520 }
            }
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChangeLocal}
              onEdgesChange={onEdgesChangeLocal}
              onConnect={onConnect}
              nodeTypes={nodeTypes}
              onInit={(instance) => { reactFlowInstanceRef.current = instance; }}
              fitView
              fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
              defaultViewport={{ x: 0, y: 0, zoom: 1 }}
              defaultEdgeOptions={{ type: 'smoothstep' }}
              proOptions={{ hideAttribution: true }}
              style={
                isChatbotMode
                  ? { width: '100%', height: '100%' }
                  : { width: '100%', height: 520 }
              }
            >
              <Background variant="dots" gap={24} size={1} color="#cbd5e1" />
              <Controls showInteractive={false} />
              <MiniMap nodeColor="#2563eb" maskColor="rgba(0,0,0,0.06)" />
              {nodes.length > 0 && (
                <Panel position="top-right" style={{ marginTop: 12, marginRight: 12 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button
                      type="button"
                      onClick={fitViewToNodes}
                      className="flow-toolbar-btn flow-toolbar-btn--message"
                      style={{ fontSize: 9, minWidth: 70, marginBottom: 0 }}
                    >
                      Centralizar blocos
                    </button>
                    <button
                      type="button"
                      onClick={removeSelected}
                      disabled={!hasSelection}
                      className="flow-toolbar-btn flow-toolbar-btn--end"
                      style={{
                        fontSize: 9,
                        minWidth: 65,
                        marginBottom: 0,
                        opacity: hasSelection ? 1 : 0.5,
                        cursor: hasSelection ? 'pointer' : 'not-allowed',
                      }}
                    >
                      Apagar selecionado
                    </button>
                    <button
                      type="button"
                      onClick={clearFlow}
                      className="flow-toolbar-btn flow-toolbar-btn--action"
                      style={{ fontSize: 9, minWidth: 55, marginBottom: 0 }}
                    >
                      Limpar fluxo
                    </button>
                    <button
                      type="button"
                      onClick={deleteAllFlowsInDb}
                      className="flow-toolbar-btn flow-toolbar-btn--end"
                      style={{ fontSize: 9, minWidth: 60, marginBottom: 0 }}
                      title="Apaga todos os fluxos no banco; depois Salvar grava só o fluxo do canvas"
                    >
                      Apagar fluxos no banco
                    </button>
                  </div>
                </Panel>
              )}
              <Panel position="top-left" style={{ marginTop: 12, marginLeft: 12 }}>
              <div className="flow-toolbar-card">
                <div className="flow-toolbar-title">Adicionar ao canvas</div>
                <p className="flow-toolbar-hint">Clique no bloco → depois conecte as bolinhas (●) entre eles.</p>
                <button type="button" onClick={() => addNode('start')} className="flow-toolbar-btn flow-toolbar-btn--start" title="Ponto de entrada">+ Início</button>
                <button type="button" onClick={() => addNode('message')} className="flow-toolbar-btn flow-toolbar-btn--message" title="Texto + botões (cada botão pode levar a um bloco diferente)">+ Mensagem</button>
                <button type="button" onClick={() => addNode('questionnaire')} className="flow-toolbar-btn flow-toolbar-btn--questionnaire" title="Coletar nome, e-mail, etc.">+ Questionário</button>
                <button type="button" onClick={() => addNode('condition')} className="flow-toolbar-btn flow-toolbar-btn--condition" title="Sim / Não">+ Condição</button>
                <button type="button" onClick={() => addNode('lead')} className="flow-toolbar-btn flow-toolbar-btn--lead" title="Salvar lead no banco">+ Salvar lead</button>
                <button type="button" onClick={() => addNode('action')} className="flow-toolbar-btn flow-toolbar-btn--action" title="Ação customizada">+ Ação</button>
                <button type="button" onClick={() => addNode('end')} className="flow-toolbar-btn flow-toolbar-btn--end" title="Encerrar">+ Finalizar</button>
              </div>
            </Panel>
              {nodes.length === 0 && (
                <Panel position="top-center" style={{ marginTop: 100 }}>
                  <div className="flow-empty-state">
                    <div className="flow-empty-icon">◇</div>
                    <h2>Comece adicionando um bloco</h2>
                    <p><strong>1.</strong> Clique em &quot;+ Início&quot; e depois em &quot;+ Mensagem&quot; (ou outro bloco) nos botões à esquerda.</p>
                    <p><strong>2.</strong> Conecte os blocos: arraste da <strong>bolinha (●)</strong> da direita de um bloco até a bolinha da esquerda do próximo.</p>
                    <p><strong>3.</strong> Em &quot;Mensagem&quot;, cada botão pode ter sua própria bolinha — conecte cada uma ao bloco que deve rodar quando a pessoa clicar naquele botão.</p>
                  </div>
                </Panel>
              )}
            </ReactFlow>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <FlowBuilderInner />
    </ReactFlowProvider>
  );
}
