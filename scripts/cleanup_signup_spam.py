"""
Remove contas de cadastro spam (onboarding sem ativação).

Uso (na raiz do projeto, com SUPABASE_URL/SUPABASE_KEY):

  python scripts/cleanup_signup_spam.py
  python scripts/cleanup_signup_spam.py --since 2026-05-20
  python scripts/cleanup_signup_spam.py --apply

Por padrão dry-run: apenas lista candidatos.

No servidor (venv):

  cd ~/agente-ia
  ./venv/bin/python3 scripts/cleanup_signup_spam.py --since 2026-05-20
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Raiz do projeto (agente-ia/) para imports database.* e services.*
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database.models import ClienteModel, Tables
from database.supabase_sq import supabase


def _parse_since(value: str | None) -> str:
    if value:
        return value.strip()[:10]
    return date.today().isoformat()


def _err_missing_column(exc: BaseException, column: str) -> bool:
    text = str(exc).lower()
    return column.lower() in text or "42703" in text


def _fetch_candidates(since_iso: str) -> list[dict]:
    if supabase is None:
        raise RuntimeError("Supabase não configurado (SUPABASE_URL/SUPABASE_KEY).")

    start = f"{since_iso}T00:00:00+00:00"
    base_cols = (
        f"{ClienteModel.ID},{ClienteModel.EMAIL},{ClienteModel.AUTH_ID},"
        f"{ClienteModel.BILLING_STATUS},{ClienteModel.CRIADO_EM}"
    )

    def _run(*, with_activated_filter: bool):
        cols = base_cols
        if with_activated_filter:
            cols = f"{base_cols},{ClienteModel.ACTIVATED_AT}"
        q = (
            supabase.table(Tables.CLIENTES)
            .select(cols)
            .eq(ClienteModel.BILLING_STATUS, "onboarding")
            .gte(ClienteModel.CRIADO_EM, start)
        )
        if with_activated_filter:
            q = q.is_(ClienteModel.ACTIVATED_AT, "null")
        return q.order(ClienteModel.CRIADO_EM, desc=True).execute()

    try:
        res = _run(with_activated_filter=True)
        return res.data or []
    except Exception as e:
        if not _err_missing_column(e, ClienteModel.ACTIVATED_AT):
            raise
        print(
            "Aviso: coluna clientes.activated_at ausente — "
            "aplique database/migrations/023_onboarding_funnel.sql no Supabase. "
            "Listando só por billing_status=onboarding.",
            file=sys.stderr,
        )
        res = _run(with_activated_filter=False)
        return res.data or []


def _delete_scheduling(cliente_id: str, dry_run: bool) -> None:
    from services.scheduling.repository import reset_agenda_catalog

    if dry_run:
        print(f"  [dry-run] scheduling reset {cliente_id}")
        return
    err = reset_agenda_catalog(cliente_id)
    if err:
        print(f"  aviso scheduling {cliente_id}: {err}")


def _delete_subscriptions(cliente_id: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] delete subscriptions cliente_id={cliente_id}")
        return
    supabase.table(Tables.SUBSCRIPTIONS).delete().eq("cliente_id", cliente_id).execute()


def _delete_cliente(cliente_id: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] delete clientes id={cliente_id}")
        return
    supabase.table(Tables.CLIENTES).delete().eq(ClienteModel.ID, cliente_id).execute()


def _delete_auth(auth_id: str | None, dry_run: bool) -> None:
    if not auth_id:
        return
    if dry_run:
        print(f"  [dry-run] delete auth user {auth_id}")
        return
    from base.supabase_auth_admin import delete_auth_user

    if not delete_auth_user(str(auth_id)):
        print(f"  aviso: não removeu auth {auth_id}")


def _purge_row(row: dict, *, apply: bool) -> None:
    cid = str(row.get(ClienteModel.ID) or row.get("id") or "")
    email = row.get(ClienteModel.EMAIL) or row.get("email") or ""
    auth_id = row.get(ClienteModel.AUTH_ID) or row.get("auth_id")
    created = row.get(ClienteModel.CRIADO_EM) or row.get("created_at") or ""
    print(f"- {cid} | {email} | created={created}")
    dry = not apply
    _delete_scheduling(cid, dry)
    _delete_subscriptions(cid, dry)
    _delete_cliente(cid, dry)
    _delete_auth(auth_id, dry)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpeza de cadastros spam (onboarding).")
    parser.add_argument("--apply", action="store_true", help="Executa exclusões (default: dry-run)")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="Data mínima de criação (UTC, default: hoje)")
    args = parser.parse_args(argv)

    since = _parse_since(args.since)
    apply = bool(args.apply)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"Modo: {mode} | since>={since}")

    try:
        rows = _fetch_candidates(since)
    except Exception as e:
        print(f"Erro ao listar: {e}", file=sys.stderr)
        return 1

    if not rows:
        print("Nenhum candidato encontrado.")
        return 0

    print(f"Candidatos: {len(rows)}")
    if not apply:
        print("Revise a lista. Para apagar: python scripts/cleanup_signup_spam.py --apply")

    for row in rows:
        try:
            _purge_row(row, apply=apply)
        except Exception as e:
            print(f"  ERRO {row.get('id')}: {e}", file=sys.stderr)

    print("Concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
