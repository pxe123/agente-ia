import secrets


def gerar_embed_key() -> str:
    return "emb_" + secrets.token_urlsafe(32)
