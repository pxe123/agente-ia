from flask import Blueprint, current_app, jsonify, make_response, request
from flask_login import login_required, current_user

from database.supabase_sq import supabase
from database.models import Tables, ClienteModel, LeadModel

import csv
from io import StringIO
from datetime import datetime, timezone, timedelta

try:
    from fpdf import FPDF
except Exception:  # pragma: no cover - lib opcional
    FPDF = None


exports_bp = Blueprint("exports", __name__, url_prefix="/painel/export")


@exports_bp.route("/clientes.csv")
@login_required
def export_clientes_csv():
    """
    Exporta lista básica de clientes do painel em CSV (abrível no Excel).
    Escopo: dados do próprio cliente logado (conta atual).
    """
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503

    cliente_id = getattr(current_user, "cliente_id", None)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    try:
        res = (
            supabase.table(Tables.CLIENTES)
            .select(
                ",".join(
                    [
                        ClienteModel.ID,
                        ClienteModel.NOME,
                        ClienteModel.EMAIL,
                        ClienteModel.PLANO,
                        ClienteModel.CRIADO_EM,
                    ]
                )
            )
            .eq(ClienteModel.ID, cliente_id)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        current_app.logger.warning("export_clientes_csv erro: %s", e)
        return jsonify({"ok": False, "erro": "Não foi possível carregar clientes."}), 500

    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["id", "nome", "email", "plano", "criado_em"])
    for r in rows:
        writer.writerow(
            [
                r.get(ClienteModel.ID, ""),
                r.get(ClienteModel.NOME, ""),
                r.get(ClienteModel.EMAIL, ""),
                r.get(ClienteModel.PLANO, ""),
                r.get(ClienteModel.CRIADO_EM, ""),
            ]
        )

    csv_data = output.getvalue()
    output.close()

    response = make_response(csv_data)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers[
        "Content-Disposition"
    ] = 'attachment; filename="clientes_painel.csv"'
    return response


def _parse_filtros_leads():
    """Lê filtros status/canal/dias da querystring e normaliza."""
    status = (request.args.get("status") or "").strip().lower()
    if status not in ("pendente", "qualificado", "desqualificado", ""):
        status = ""
    canal = (request.args.get("canal") or "").strip().lower()
    if canal not in ("whatsapp", "instagram", "facebook", "messenger", "website"):
        canal = ""
    try:
        dias = int(request.args.get("dias") or "30")
    except ValueError:
        dias = 30
    dias = max(1, min(dias, 365))
    return status, canal, dias


def _buscar_leads(cliente_id: str, status: str, canal: str, dias: int):
    """Busca leads para export considerando filtros."""
    if supabase is None:
        return []
    inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        q = (
            supabase.table(Tables.LEADS)
            .select(
                ",".join(
                    [
                        LeadModel.ID,
                        LeadModel.NOME,
                        LeadModel.EMAIL,
                        LeadModel.TELEFONE,
                        LeadModel.CANAL,
                        LeadModel.STATUS,
                        LeadModel.CREATED_AT,
                    ]
                )
            )
            .eq(LeadModel.CLIENTE_ID, cliente_id)
            .gte(LeadModel.CREATED_AT, inicio)
            .order(LeadModel.CREATED_AT, desc=True)
        )
        if status:
            if status == "pendente":
                q = q.or_(f"{LeadModel.STATUS}.is.null,{LeadModel.STATUS}.eq.pendente")
            else:
                q = q.eq(LeadModel.STATUS, status)
        if canal:
            q = q.eq(LeadModel.CANAL, canal)
        res = q.execute()
        return res.data or []
    except Exception as e:
        current_app.logger.warning("export_leads erro: %s", e)
        return []


@exports_bp.route("/leads.csv")
@login_required
def export_leads_csv():
    """
    Exporta os leads do cliente em CSV (abrível no Excel).
    Filtros via querystring: ?status=qualificado&dias=30
    """
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503

    cliente_id = getattr(current_user, "cliente_id", None)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    status, canal, dias = _parse_filtros_leads()
    rows = _buscar_leads(cliente_id, status, canal, dias)

    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["nome", "email", "telefone", "canal", "status", "criado_em"])
    for r in rows:
        writer.writerow(
            [
                r.get(LeadModel.NOME, ""),
                r.get(LeadModel.EMAIL, ""),
                r.get(LeadModel.TELEFONE, ""),
                r.get(LeadModel.CANAL, ""),
                (r.get(LeadModel.STATUS) or "pendente"),
                r.get(LeadModel.CREATED_AT, ""),
            ]
        )

    csv_data = output.getvalue()
    output.close()

    response = make_response(csv_data)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers[
        "Content-Disposition"
    ] = 'attachment; filename="leads_painel.csv"'
    return response


@exports_bp.route("/leads.pdf")
@login_required
def export_leads_pdf():
    """
    Exporta um relatório simples de leads em PDF (tabela compacta).
    Filtros via querystring: ?status=qualificado&dias=30
    """
    if FPDF is None:
        return jsonify({"ok": False, "erro": "Biblioteca FPDF não instalada no servidor."}), 503
    if supabase is None:
        return jsonify({"ok": False, "erro": "Supabase não configurado no servidor."}), 503

    cliente_id = getattr(current_user, "cliente_id", None)
    if not cliente_id:
        return jsonify({"ok": False, "erro": "Cliente não identificado na sessão."}), 400

    status, canal, dias = _parse_filtros_leads()
    rows = _buscar_leads(cliente_id, status, canal, dias)

    try:
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Relatorio de Leads", ln=1)
        pdf.set_font("Helvetica", "", 10)
        filtro_txt = f"Periodo: ultimos {dias} dias"
        if status:
            filtro_txt += f" | Status: {status}"
        pdf.cell(0, 8, filtro_txt, ln=1)
        pdf.ln(2)

        # Cabeçalho
        pdf.set_font("Helvetica", "B", 9)
        col_widths = [40, 50, 35, 25, 25, 35]
        headers = ["Nome", "Email", "Telefone", "Canal", "Status", "Criado em"]
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 7, str(h), border=1)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for r in rows:
            valores = [
                (r.get(LeadModel.NOME, "") or "")[:28],
                (r.get(LeadModel.EMAIL, "") or "")[:34],
                (r.get(LeadModel.TELEFONE, "") or "")[:20],
                (r.get(LeadModel.CANAL, "") or "")[:14],
                (r.get(LeadModel.STATUS, "") or "pendente")[:14],
                (str(r.get(LeadModel.CREATED_AT, "")) or "")[:20],
            ]
            for w, val in zip(col_widths, valores):
                pdf.cell(w, 6, str(val)[:30] if val else "", border=1)
            pdf.ln()

        # fpdf/fpdf2 variam: `output(dest="S")` pode retornar str (FPDF) ou bytes/bytearray (fpdf2).
        out = pdf.output(dest="S")
        pdf_bytes = out.encode("latin-1") if isinstance(out, str) else bytes(out)
    except Exception as e:
        current_app.logger.exception("export_leads_pdf: %s", e)
        return jsonify({"ok": False, "erro": f"Erro ao gerar PDF: {e!s}"}), 500

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers[
        "Content-Disposition"
    ] = 'attachment; filename="leads_painel.pdf"'
    return response

