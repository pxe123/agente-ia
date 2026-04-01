# services/routing_service.py
from database.supabase_sq import supabase
from database.models import Tables, ClienteModel
from services.meta_send import (
    send_whatsapp_cloud,
    send_whatsapp_cloud_interactive_buttons,
    send_instagram,
    send_messenger,
)
from services.sent_message_cache import registrar_envio
from services.entitlements import can_use_channel
from services.app_settings import get_global_settings
from base.config import settings


class RoutingService:
    @staticmethod
    def enviar_resposta(canal, instancia, remote_id, texto, cliente_id=None, anexo_base64=None, anexo_mimetype=None, anexo_filename=None) -> tuple[bool, str | None]:
        """
        Roteia o envio: WhatsApp (WAHA), Instagram ou Messenger (Meta).
        anexo_base64, anexo_mimetype, anexo_filename: opcionais; se presentes, envia mídia (WhatsApp via WAHA).
        Retorna (True, None) em sucesso ou (False, mensagem_erro) em falha.
        """
        try:
            cid = str(cliente_id).strip() if cliente_id else ""
            if cid:
                if canal == "whatsapp" and not can_use_channel(cid, "whatsapp"):
                    return (
                        False,
                        "WhatsApp indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )
                if canal == "instagram" and not can_use_channel(cid, "instagram"):
                    return (
                        False,
                        "Instagram indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )
                if canal == "facebook" and not can_use_channel(cid, "facebook"):
                    return (
                        False,
                        "Messenger indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )

            cliente = None
            if cliente_id:
                r = supabase.table(Tables.CLIENTES).select("*").eq("id", cliente_id).execute()
                if r.data and len(r.data) > 0:
                    cliente = r.data[0]
            session_name = (instancia or (cliente or {}).get(ClienteModel.WHATSAPP_INSTANCIA) or "default").strip()

            if canal == "whatsapp":
                if not getattr(settings, "WAHA_URL", None) or not getattr(settings, "WAHA_API_KEY", None):
                    return (False, "WhatsApp (WAHA) não configurado. Defina WAHA_URL e WAHA_API_KEY no .env.")
                if anexo_base64 and anexo_mimetype:
                    from integrations.whatsapp.waha_client import enviar_imagem, enviar_documento, enviar_audio
                    mimetype = (anexo_mimetype or "").strip().lower()
                    filename = (anexo_filename or "arquivo").strip() or "arquivo"
                    caption = (texto or "").strip()
                    if mimetype.startswith("image/"):
                        ok, err = enviar_imagem(remote_id, anexo_base64, mimetype=mimetype, filename=filename, caption=caption, session=session_name)
                    elif mimetype.startswith("audio/"):
                        ok, err = enviar_audio(remote_id, anexo_base64, mimetype=mimetype, filename=filename, caption=caption, session=session_name, convert=True)
                    else:
                        ok, err = enviar_documento(remote_id, anexo_base64, mimetype=mimetype, filename=filename, caption=caption, session=session_name)
                    return (ok, err)
                from integrations.whatsapp.waha_client import enviar_texto as waha_enviar_texto
                ok, err = waha_enviar_texto(remote_id, texto or "", session=session_name)
                # Evitar duplicar no painel quando o WAHA devolver o eco fromMe=true no webhook:
                if ok and cliente_id:
                    try:
                        # #region agent log
                        try:
                            import json as _json, time as _t
                            rid_last4 = "".join([c for c in str(remote_id) if c.isdigit()])[-4:] if remote_id else ""
                            _p = {
                                "sessionId": "3bd729",
                                "runId": "pre-fix",
                                "hypothesisId": "H4",
                                "location": "services/routing_service.py",
                                "message": "routing_register_envio_text",
                                "data": {"canal": canal, "remoteLast4": rid_last4, "textoLen": len(texto or "")},
                                "timestamp": int(_t.time() * 1000),
                            }
                            try:
                                print("[DBG3bd729] " + _json.dumps(_p, ensure_ascii=False), flush=True)
                            except Exception:
                                pass
                            with open("debug-3bd729.log", "a", encoding="utf-8") as f:
                                f.write(_json.dumps(_p, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                        # #endregion
                        registrar_envio(cliente_id, remote_id, texto or "")
                    except Exception:
                        pass
                return (ok, err)

            if canal == "instagram" and cliente and cliente.get(ClienteModel.META_IG_TOKEN) and cliente.get(ClienteModel.META_IG_PAGE_ID):
                ok, err = send_instagram(
                    cliente[ClienteModel.META_IG_PAGE_ID],
                    cliente[ClienteModel.META_IG_TOKEN],
                    remote_id,
                    texto,
                )
                return (ok, None) if ok else (False, err or "Falha ao enviar pelo Instagram.")

            if canal == "facebook" and cliente and cliente.get(ClienteModel.META_FB_TOKEN) and cliente.get(ClienteModel.META_FB_PAGE_ID):
                page_id = (cliente.get(ClienteModel.META_FB_PAGE_ID) or "").strip()
                if not page_id or "@" in str(page_id):
                    print("[RoutingService] Page ID inválido (vazio ou e-mail). Use o ID numérico da página em Conexões.", flush=True)
                    return (False, "Messenger: ID da página inválido. Em Conexões, use o ID numérico da página (Page ID), não o e-mail.")
                print(f"[RoutingService] Enviando Messenger: page_id={page_id} psid={remote_id}", flush=True)
                ok = send_messenger(
                    page_id,
                    cliente[ClienteModel.META_FB_TOKEN],
                    remote_id,
                    texto,
                )
                return (ok, None) if ok else (False, "Falha ao enviar pelo Messenger.")

            if canal == "instagram":
                print("[RoutingService] Instagram: cliente sem credenciais Meta configuradas.", flush=True)
                return (False, "Instagram não configurado em Conexões.")
            if canal == "facebook":
                print("[RoutingService] Messenger: cliente sem credenciais Meta configuradas.", flush=True)
                return (False, "Messenger não configurado em Conexões.")
            print(f"[RoutingService] Canal {canal} não suportado ou sem credenciais.", flush=True)
            return (False, f"Canal {canal} não suportado ou sem credenciais.")
        except Exception as e:
            print(f"[RoutingService] Erro no roteador: {e}", flush=True)
            return (False, str(e))

    @staticmethod
    def enviar_resposta_interativa(
        canal, instancia, remote_id, body_text, buttons, cliente_id=None
    ) -> tuple[bool, str | None]:
        """
        Envia mensagem com botões quando possível.
        buttons: [ {"id": "x", "title": "Sim"}, ... ] (até 3).
        WhatsApp Meta: interactive; WhatsApp WAHA: texto com "Responda: 1. X 2. Y".
        Retorna (True, None) ou (False, mensagem_erro).
        """
        try:
            cid = str(cliente_id).strip() if cliente_id else ""
            if cid:
                if canal == "whatsapp" and not can_use_channel(cid, "whatsapp"):
                    return (
                        False,
                        "WhatsApp indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )
                if canal == "instagram" and not can_use_channel(cid, "instagram"):
                    return (
                        False,
                        "Instagram indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )
                if canal == "facebook" and not can_use_channel(cid, "facebook"):
                    return (
                        False,
                        "Messenger indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                    )
            elif canal == "whatsapp" and not get_global_settings().get("whatsapp_enabled", True):
                return (
                    False,
                    "WhatsApp indisponível: verifique o plano ou se o canal foi desativado globalmente pelo administrador.",
                )

            cliente = None
            if cliente_id and supabase:
                r = supabase.table(Tables.CLIENTES).select("*").eq("id", cliente_id).execute()
                if r.data and len(r.data) > 0:
                    cliente = r.data[0]
            session_name = (instancia or (cliente or {}).get(ClienteModel.WHATSAPP_INSTANCIA) or "default").strip()

            if canal == "whatsapp":
                # WhatsApp Cloud (Meta): botões nativos
                if cliente and cliente.get(ClienteModel.META_WA_PHONE_NUMBER_ID) and cliente.get(ClienteModel.META_WA_TOKEN):
                    ok, err = send_whatsapp_cloud_interactive_buttons(
                        cliente[ClienteModel.META_WA_PHONE_NUMBER_ID],
                        cliente[ClienteModel.META_WA_TOKEN],
                        remote_id,
                        body_text or " ",
                        buttons or [],
                    )
                    return (ok, err)
                # WAHA: tenta botões nativos (POST /api/sendButtons, motor NOWEB); se falhar, fallback texto
                if getattr(settings, "WAHA_URL", None) and getattr(settings, "WAHA_API_KEY", None):
                    if buttons and len(buttons) > 0:
                        from integrations.whatsapp.waha_client import enviar_botoes as waha_enviar_botoes
                        ok, err = waha_enviar_botoes(
                            remote_id,
                            body_text or " ",
                            buttons[:3],
                            session=session_name,
                        )
                        if ok:
                            if cliente_id:
                                try:
                                    registrar_envio(cliente_id, remote_id, body_text or " ")
                                except Exception:
                                    pass
                            return (True, None)
                    from integrations.whatsapp.waha_client import enviar_texto as waha_enviar_texto
                    # Fallback em texto com layout amigável:
                    # Olá, tudo bem?
                    #
                    # 1) Sim
                    # 2) Não
                    #
                    # Responda com o número ou o texto.
                    linhas: list[str] = []
                    if (body_text or "").strip():
                        linhas.append((body_text or "").strip())
                    if buttons and len(buttons) > 0:
                        if linhas:
                            linhas.append("")
                        for i, b in enumerate(buttons[:3], 1):
                            title = (b.get("title") or b.get("label") or "").strip() or str(i)
                            linhas.append(f"{i}) {title}")
                        linhas.append("")
                        linhas.append("Responda com o número ou o texto.")
                    texto_fallback = "\n".join(linhas).strip() or " "
                    ok, err = waha_enviar_texto(
                        remote_id,
                        texto_fallback,
                        session=session_name,
                    )
                    if ok and cliente_id:
                        try:
                            registrar_envio(cliente_id, remote_id, texto_fallback)
                        except Exception:
                            pass
                    return (ok, err)
                return (False, "WhatsApp não configurado.")

            # Instagram/Messenger: sem interactive; envia texto + opções em linha
            if canal in ("instagram", "facebook") and cliente:
                if canal == "instagram" and cliente.get(ClienteModel.META_IG_TOKEN) and cliente.get(ClienteModel.META_IG_PAGE_ID):
                    text = body_text or ""
                    if buttons and len(buttons) > 0:
                        text += "\n\n" + " | ".join((b.get("title") or b.get("label") or "") for b in buttons[:3])
                    ok, err = send_instagram(
                        cliente[ClienteModel.META_IG_PAGE_ID],
                        cliente[ClienteModel.META_IG_TOKEN],
                        remote_id,
                        text.strip() or " ",
                    )
                    return (ok, None) if ok else (False, err or "Falha Instagram.")
                if canal == "facebook" and cliente.get(ClienteModel.META_FB_TOKEN) and cliente.get(ClienteModel.META_FB_PAGE_ID):
                    text = body_text or ""
                    if buttons and len(buttons) > 0:
                        text += "\n\n" + " | ".join((b.get("title") or b.get("label") or "") for b in buttons[:3])
                    ok = send_messenger(
                        cliente[ClienteModel.META_FB_PAGE_ID],
                        cliente[ClienteModel.META_FB_TOKEN],
                        remote_id,
                        text.strip() or " ",
                    )
                    return (ok, None) if ok else (False, "Falha Messenger.")
            return (False, f"Canal {canal} sem credenciais para envio interativo.")
        except Exception as e:
            print(f"[RoutingService] Erro no roteador (interativo): {e}", flush=True)
            return (False, str(e))