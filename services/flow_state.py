# services/flow_state.py
"""
Acesso ao estado do fluxo e resolução do fluxo por canal: get_flow, get_state, set_state, clear_state.
Depende de database e de flow_helpers (canal_to_channel).
"""
from __future__ import annotations

from datetime import datetime, timezone

from database.supabase_sq import supabase
from database.models import Tables, FlowModel, FlowUserStateModel, ChatbotModel

from services.flow_helpers import canal_to_channel


def get_flow(cliente_id: str, canal: str) -> tuple[dict | None, str | None]:
    """
    Retorna (flow_json, flow_id) para o canal.
    Primeiro tenta fluxo de chatbot com channel; depois default do chatbot; depois legado por canal.
    """
    if not supabase or not cliente_id:
        return None, None
    channel = canal_to_channel(canal)

    # 1) Fluxo de chatbot cujo channels contém este canal
    try:
        cb = (
            supabase.table(Tables.CHATBOTS)
            .select(ChatbotModel.ID, ChatbotModel.CHANNELS)
            .eq(ChatbotModel.CLIENTE_ID, cliente_id)
            .execute()
        )
        chatbot_id = None
        for row_cb in (cb.data or []):
            ch_val = row_cb.get(ChatbotModel.CHANNELS)
            match = False
            if isinstance(ch_val, list):
                match = channel in [str(c).strip().lower() for c in ch_val]
            elif isinstance(ch_val, str):
                ch_lower = ch_val.strip().lower()
                if ch_lower == channel:
                    match = True
                elif f'"{channel}"' in ch_lower or f"'{channel}'" in ch_lower or channel in ch_lower.split(","):
                    match = True
            if match:
                chatbot_id = row_cb.get(ChatbotModel.ID)
                break
        if chatbot_id:
            # 1.a) Fluxo específico por canal
            try:
                r = (
                    supabase.table(Tables.FLOWS)
                    .select(FlowModel.ID, FlowModel.FLOW_JSON, FlowModel.CHANNEL)
                    .eq(FlowModel.CLIENTE_ID, cliente_id)
                    .eq(FlowModel.CHATBOT_ID, chatbot_id)
                    .eq(FlowModel.CHANNEL, channel)
                    .limit(1)
                    .execute()
                )
                if r.data and len(r.data) > 0:
                    row = r.data[0]
                    return (row.get(FlowModel.FLOW_JSON) or {}), str(row.get(FlowModel.ID) or "")
            except Exception as e:
                print(f"[FlowState] get_flow chatbot canal channel={channel} erro: {e}", flush=True)
            # 1.b) Fluxo default do chatbot
            try:
                r_def = (
                    supabase.table(Tables.FLOWS)
                    .select(FlowModel.ID, FlowModel.FLOW_JSON, FlowModel.CHANNEL)
                    .eq(FlowModel.CLIENTE_ID, cliente_id)
                    .eq(FlowModel.CHATBOT_ID, chatbot_id)
                    .eq(FlowModel.CHANNEL, "default")
                    .limit(1)
                    .execute()
                )
                if r_def.data and len(r_def.data) > 0:
                    row = r_def.data[0]
                    return (row.get(FlowModel.FLOW_JSON) or {}), str(row.get(FlowModel.ID) or "")
            except Exception as e:
                print(f"[FlowState] get_flow chatbot default erro: {e}", flush=True)
            # 1.c) Qualquer fluxo do chatbot
            try:
                r_any = (
                    supabase.table(Tables.FLOWS)
                    .select(FlowModel.ID, FlowModel.FLOW_JSON)
                    .eq(FlowModel.CLIENTE_ID, cliente_id)
                    .eq(FlowModel.CHATBOT_ID, chatbot_id)
                    .limit(1)
                    .execute()
                )
                if r_any.data and len(r_any.data) > 0:
                    row = r_any.data[0]
                    return (row.get(FlowModel.FLOW_JSON) or {}), str(row.get(FlowModel.ID) or "")
            except Exception as e:
                print(f"[FlowState] get_flow chatbot any-flow erro: {e}", flush=True)
    except Exception as e:
        print(f"[FlowState] get_flow chatbot lookup channel={channel} erro: {e}", flush=True)

    # 2) Fluxo legado por canal (chatbot_id IS NULL)
    try:
        r = (
            supabase.table(Tables.FLOWS)
            .select(FlowModel.ID, FlowModel.FLOW_JSON, FlowModel.CHATBOT_ID)
            .eq(FlowModel.CLIENTE_ID, cliente_id)
            .eq(FlowModel.CHANNEL, channel)
            .limit(5)
            .execute()
        )
        for row in (r.data or []):
            if row.get(FlowModel.CHATBOT_ID) is None:
                return (row.get(FlowModel.FLOW_JSON) or {}), str(row.get(FlowModel.ID) or "")
    except Exception as e:
        print(f"[FlowState] get_flow legado channel={channel} erro: {e}", flush=True)
    return None, None


def get_state(cliente_id: str, canal: str, remote_id: str) -> tuple[str | None, str | None, dict]:
    """Retorna (current_node_id, flow_id, collected_data). (None, flow_id, {}) = ainda não iniciado."""
    if not supabase or not cliente_id or not canal or not remote_id:
        return None, None, {}
    try:
        r = supabase.table(Tables.FLOW_USER_STATE).select(
            FlowUserStateModel.CURRENT_NODE_ID,
            FlowUserStateModel.FLOW_ID,
            FlowUserStateModel.COLLECTED_DATA,
        ).eq(FlowUserStateModel.CLIENTE_ID, cliente_id).eq(FlowUserStateModel.CANAL, canal).eq(FlowUserStateModel.REMOTE_ID, remote_id).limit(1).execute()
        if r.data and len(r.data) > 0:
            row = r.data[0]
            return (
                row.get(FlowUserStateModel.CURRENT_NODE_ID),
                row.get(FlowUserStateModel.FLOW_ID),
                row.get(FlowUserStateModel.COLLECTED_DATA) or {},
            )
    except Exception as e:
        print(f"[FlowState] get_state erro: {e}", flush=True)
    return None, None, {}


def set_state(
    cliente_id: str,
    canal: str,
    remote_id: str,
    flow_id: str,
    current_node_id: str | None,
    collected_data: dict | None = None,
) -> None:
    if not supabase or not cliente_id or not flow_id:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            FlowUserStateModel.CLIENTE_ID: cliente_id,
            FlowUserStateModel.CANAL: canal,
            FlowUserStateModel.REMOTE_ID: remote_id,
            FlowUserStateModel.FLOW_ID: flow_id,
            FlowUserStateModel.CURRENT_NODE_ID: current_node_id,
            FlowUserStateModel.UPDATED_AT: now,
        }
        if collected_data is not None and isinstance(collected_data, dict):
            payload[FlowUserStateModel.COLLECTED_DATA] = collected_data
        supabase.table(Tables.FLOW_USER_STATE).upsert(payload, on_conflict="cliente_id,canal,remote_id").execute()
    except Exception as e:
        print(f"[FlowState] set_state erro: {e}", flush=True)


def clear_state(cliente_id: str, canal: str, remote_id: str) -> None:
    """Remove o estado do fluxo para esta sessão (reiniciar atendimento)."""
    if not supabase or not cliente_id or not canal or not remote_id:
        return
    try:
        supabase.table(Tables.FLOW_USER_STATE).delete().eq(FlowUserStateModel.CLIENTE_ID, cliente_id).eq(FlowUserStateModel.CANAL, canal).eq(FlowUserStateModel.REMOTE_ID, remote_id).execute()
    except Exception as e:
        print(f"[FlowState] clear_state erro: {e}", flush=True)
