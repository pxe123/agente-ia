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
import { AgendamentoIANode } from './nodes/AgendamentoIANode';
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
  agendamento_ia: AgendamentoIANode,
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

function isMessageNode(n) {
  return n && n.type === 'message';
}

function getMessageButtonsCount(n) {
  const btns = n?.data?.buttons;
  return Array.isArray(btns) ? btns.length : 0;
}

// Detecta um padrão comum de configuração incorreta:
// Mensagem com botões conectando para outra Mensagem (sequência) faz o fluxo "parar" esperando clique,
// impedindo que as próximas mensagens sejam enviadas automaticamente.
function messageSequenceWarnings(nodes, edges) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Map();
  edges.forEach((e) => {
    if (!e?.source || !e?.target) return;
    if (!out.has(e.source)) out.set(e.source, []);
    out.get(e.source).push(e);
  });

  const warnings = [];
  edges.forEach((e) => {
    const src = byId.get(e.source);
    const dst = byId.get(e.target);
    if (!isMessageNode(src) || !isMessageNode(dst)) return;
    const btnCount = getMessageButtonsCount(src);
    if (btnCount <= 0) return;
    // Se existe uma aresta de um botão levando para outra Mensagem, é um forte indício de que o usuário
    // queria uma sequência (mensagens seguidas) mas colocou botões cedo demais.
    const sh = (e.sourceHandle || '').toString();
    const isBtnHandle = /^btn_\d+$/.test(sh);
    if (!isBtnHandle) return;
    warnings.push({
      type: 'buttons_before_sequence',
      sourceId: src.id,
      targetId: dst.id,
    });
  });

  // Deduplicar
  const seen = new Set();
  const uniq = [];
  for (const w of warnings) {
    const k = `${w.type}:${w.sourceId}:${w.targetId}`;
    if (seen.has(k)) continue;
    seen.add(k);
    uniq.push(w);
  }
  return uniq;
}

function isBtnHandle(handle) {
  const sh = (handle || '').toString();
  return /^btn_\d+$/.test(sh);
}

function isDefaultHandle(handle) {
  const sh = (handle || '').toString();
  return sh === '' || sh === 'default';
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
  const [validationWarning, setValidationWarning] = useState('');
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
              type: (n.type && ['message', 'condition', 'action', 'start', 'end', 'questionnaire', 'lead', 'agendamento_ia'].includes(n.type)) ? n.type : 'message',
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
      const warnings = messageSequenceWarnings(nodesToSave, edgesToSave);
      if (soltos.length > 0) {
        setValidationError(
          `Alguns blocos não estão conectados. Arraste da bolinha (●) de um bloco até a bolinha de outro para ligar. Desconectados: ${soltos.join(', ')}`
        );
      } else {
        setValidationError('');
      }
      if (warnings.length > 0) {
        setValidationWarning(
          `Aviso: Há botões em uma mensagem antes de outras mensagens na sequência (${warnings.length}). Botões fazem o fluxo aguardar clique e podem impedir o envio das próximas mensagens. Dica: coloque botões apenas no último bloco da sequência.`
        );
      } else {
        setValidationWarning('');
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

  const autoFixMoveButtonsToLastMessageInSequence = useCallback(() => {
    const nodesNow = nodesRef.current || [];
    const edgesNow = edgesRef.current || [];
    const byId = new Map(nodesNow.map((n) => [n.id, n]));

    const out = new Map();
    edgesNow.forEach((e) => {
      if (!e?.source || !e?.target) return;
      if (!out.has(e.source)) out.set(e.source, []);
      out.get(e.source).push(e);
    });

    const fixCandidates = [];
    edgesNow.forEach((e) => {
      const src = byId.get(e.source);
      const dst = byId.get(e.target);
      if (!isMessageNode(src) || !isMessageNode(dst)) return;
      if (getMessageButtonsCount(src) <= 0) return;
      if (!isBtnHandle(e.sourceHandle)) return;
      const outEdges = out.get(src.id) || [];
      // Seguro: só corrigir quando o bloco com botões tem apenas 1 saída total (provável "sequência" sem querer)
      if (outEdges.length !== 1) return;
      fixCandidates.push({ edge: e, sourceId: src.id, firstTargetId: dst.id });
    });

    if (fixCandidates.length === 0) {
      window.alert('Não encontrei um caso seguro para corrigir automaticamente. Dica: coloque os botões apenas no último bloco da sequência.');
      return;
    }

    const nextNodes = nodesNow.map((n) => ({ ...n, data: n.data != null ? { ...n.data } : {} }));
    const nextEdges = edgesNow.map((e) => ({ ...e }));
    const nextById = new Map(nextNodes.map((n) => [n.id, n]));

    for (const c of fixCandidates) {
      const src = nextById.get(c.sourceId);
      if (!src || !isMessageNode(src)) continue;
      const srcButtons = Array.isArray(src.data?.buttons) ? src.data.buttons : [];
      if (srcButtons.length === 0) continue;

      // Descobrir último Message em cadeia via saída default
      let currentId = c.firstTargetId;
      while (true) {
        const current = nextById.get(currentId);
        if (!current || !isMessageNode(current)) break;
        if (getMessageButtonsCount(current) > 0) break; // já tem botões → não mexe

        const outEdges = nextEdges.filter((e) => e.source === currentId);
        const defaultEdges = outEdges.filter((e) => isDefaultHandle(e.sourceHandle));
        if (defaultEdges.length !== 1) break;
        const nextTarget = defaultEdges[0].target;
        const nextNode = nextById.get(nextTarget);
        if (!nextNode || !isMessageNode(nextNode)) break;
        currentId = nextTarget;
      }

      const last = nextById.get(currentId);
      if (!last || !isMessageNode(last)) continue;
      if (getMessageButtonsCount(last) > 0) continue; // não sobrescrever botões existentes

      // Mover botões
      last.data = { ...(last.data || {}), buttons: srcButtons.slice(0, 3) };
      src.data = { ...(src.data || {}), buttons: [] };

      // Converter a aresta de botão para default (agora o src terá saída default)
      for (const e of nextEdges) {
        if (e.source === c.sourceId && e.target === c.firstTargetId && isBtnHandle(e.sourceHandle)) {
          e.sourceHandle = 'default';
        }
      }
    }

    setNodes(nextNodes);
    setEdges(nextEdges);
    setTimeout(() => {
      try {
        setValidationWarning('');
      } catch (_) {}
    }, 0);
    scheduleSave();
    window.alert('Correção aplicada: movi botões para o último bloco da sequência (apenas nos casos seguros).');
  }, [setNodes, setEdges, scheduleSave]);

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
    // Atualiza avisos rapidamente após conectar
    try {
      const nextEdges = [...(edgesRef.current || []), { id: `e_${Date.now()}`, ...params }];
      const warnings = messageSequenceWarnings(nodesRef.current || [], nextEdges);
      setValidationWarning(
        warnings.length > 0
          ? `Aviso: Há botões em uma mensagem antes de outras mensagens na sequência (${warnings.length}). Botões fazem o fluxo aguardar clique e podem impedir o envio das próximas mensagens. Dica: coloque botões apenas no último bloco da sequência.`
          : ''
      );
    } catch (_) {}
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
        agendamento_ia: {
          label: 'Agendamento (IA)',
          notes: '',
          context_extra: '',
          message_template: 'Escolha: {{slot_list}} / digite 1, 2 ou 3. Confirme com sim para marcar.',
          message_templates: JSON.stringify({
            default: 'Siga as instruções. {{slot_list}}',
            needs_input: 'Opções: {{slot_list}}',
            ok: 'Concluído. Data: {{start}} — fim: {{end}}. ID: {{appointment_id}}',
            error: 'Não foi possível: {{error_code}}',
            error_NO_APPOINTMENT: 'Não há agendamento para cancelar.',
            error_SLOT_TAKEN: 'O horário já foi ocupado.',
            error_NO_SLOTS: 'Sem horários livres. Tente mais tarde.',
          }, null, 0),
        },
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

  const addMessageSequenceWithChoice = useCallback(
    () => {
      const now = Date.now();
      const mkId = (suffix) => `message_${now}_${suffix}`;
      const ids = [mkId('1'), mkId('2'), mkId('3'), mkId('choice')];

      const instance = reactFlowInstanceRef.current;
      const canvasEl = canvasInnerRef.current;
      let basePos = null;
      try {
        if (instance && canvasEl && typeof canvasEl.getBoundingClientRect === 'function') {
          const r = canvasEl.getBoundingClientRect();
          const screen = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
          if (typeof instance.screenToFlowPosition === 'function') basePos = instance.screenToFlowPosition(screen);
          else if (typeof instance.project === 'function') basePos = instance.project(screen);
        }
      } catch (_) {
        basePos = null;
      }
      const startX = basePos && typeof basePos.x === 'number' ? basePos.x : 140;
      const startY = basePos && typeof basePos.y === 'number' ? basePos.y : 140;

      const newNodes = [
        { id: ids[0], type: 'message', position: { x: startX, y: startY }, data: { text: 'Plano 1: ...', buttons: [] } },
        { id: ids[1], type: 'message', position: { x: startX + 320, y: startY }, data: { text: 'Plano 2: ...', buttons: [] } },
        { id: ids[2], type: 'message', position: { x: startX + 640, y: startY }, data: { text: 'Plano 3: ...', buttons: [] } },
        {
          id: ids[3],
          type: 'message',
          position: { x: startX + 960, y: startY },
          data: {
            text: 'Qual plano você quer?',
            buttons: [{ id: 'btn_0', title: 'Plano 1' }, { id: 'btn_1', title: 'Plano 2' }, { id: 'btn_2', title: 'Plano 3' }],
          },
        },
      ];

      const newEdges = [
        { id: `e_${ids[0]}_${ids[1]}_default`, source: ids[0], target: ids[1], sourceHandle: 'default' },
        { id: `e_${ids[1]}_${ids[2]}_default`, source: ids[1], target: ids[2], sourceHandle: 'default' },
        { id: `e_${ids[2]}_${ids[3]}_default`, source: ids[2], target: ids[3], sourceHandle: 'default' },
      ];

      setNodes((nds) => [...nds, ...newNodes]);
      setEdges((eds) => [...eds, ...newEdges]);
      scheduleSave();
      setTimeout(() => {
        try {
          reactFlowInstanceRef.current?.fitView?.({ padding: 0.25, duration: 200 });
        } catch (_) {}
      }, 50);
    },
    [setNodes, setEdges, scheduleSave]
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
            <button type="button" onClick={() => addNode('agendamento_ia')} className="flow-block-btn flow-block-btn--agendamento_ia" title="Agendamento com API externa (multi-turn)">
              Agendamento IA
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
            {validationWarning && !validationError && (
              <span className="flow-header-ok" style={{ background: '#fffbeb', borderColor: '#f59e0b', color: '#b45309' }}>
                {validationWarning}{' '}
                <button
                  type="button"
                  onClick={autoFixMoveButtonsToLastMessageInSequence}
                  style={{
                    marginLeft: 8,
                    fontSize: 11,
                    padding: '4px 8px',
                    borderRadius: 8,
                    border: '1px solid #f59e0b',
                    background: '#fff',
                    color: '#92400e',
                    cursor: 'pointer',
                  }}
                  title="Move botões de um bloco intermediário para o último bloco da sequência (somente quando for seguro)."
                >
                  Corrigir automaticamente
                </button>
              </span>
            )}
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
                <button
                  type="button"
                  onClick={addMessageSequenceWithChoice}
                  className="flow-toolbar-btn flow-toolbar-btn--message"
                  title="Cria 3 mensagens em sequência e uma mensagem final com botões (escolha)"
                >
                  + Sequência (mensagens + escolha)
                </button>
                <button type="button" onClick={() => addNode('start')} className="flow-toolbar-btn flow-toolbar-btn--start" title="Ponto de entrada">+ Início</button>
                <button type="button" onClick={() => addNode('message')} className="flow-toolbar-btn flow-toolbar-btn--message" title="Texto + botões (cada botão pode levar a um bloco diferente)">+ Mensagem</button>
                <button type="button" onClick={() => addNode('questionnaire')} className="flow-toolbar-btn flow-toolbar-btn--questionnaire" title="Coletar nome, e-mail, etc.">+ Questionário</button>
                <button type="button" onClick={() => addNode('condition')} className="flow-toolbar-btn flow-toolbar-btn--condition" title="Sim / Não">+ Condição</button>
                <button type="button" onClick={() => addNode('lead')} className="flow-toolbar-btn flow-toolbar-btn--lead" title="Salvar lead no banco">+ Salvar lead</button>
                <button type="button" onClick={() => addNode('action')} className="flow-toolbar-btn flow-toolbar-btn--action" title="Ação customizada">+ Ação</button>
                <button type="button" onClick={() => addNode('agendamento_ia')} className="flow-toolbar-btn flow-toolbar-btn--agendamento_ia" title="API de agendamento (multi-turn)">+ Agendamento IA</button>
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
