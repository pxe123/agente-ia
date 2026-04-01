"""
Serviço para baixar e servir anexos de mensagens (imagens, documentos).
- Download de mídia (ex.: WAHA media.url) e gravação em pasta local.
- Rota GET /api/anexo/<filename> serve o arquivo (com verificação de dono).
"""
import os
import uuid
import requests
from flask import send_from_directory

# Extensões por MIME comum (para salvar com extensão correta)
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/plain": "txt",
    "text/csv": "csv",
    "audio/ogg": "ogg",
    "audio/ogg; codecs=opus": "ogg",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
}


def _uploads_dir():
    """Diretório base para anexos (uploads/mensagens)."""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(base, "uploads", "mensagens")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _ext_from_mime_or_name(mimetype: str, filename: str) -> str:
    """Retorna extensão (sem ponto) a partir de MIME ou nome do arquivo."""
    if mimetype:
        m = (mimetype or "").strip().lower().split(";")[0].strip()
        if m in MIME_TO_EXT:
            return MIME_TO_EXT[m]
    if filename:
        p = (filename or "").strip()
        if "." in p:
            return p.rsplit(".", 1)[-1].lower()[:10]
    return "bin"


def download_and_save_anexo(
    url: str,
    cliente_id: str,
    mimetype: str = "",
    filename: str = "",
    api_key_header: str = None,
) -> str | None:
    """
    Baixa o arquivo da URL e salva em uploads/mensagens/{cliente_id}_{uuid}.ext.
    Retorna a URL relativa para servir: /api/anexo/{cliente_id}_{uuid}.ext
    Se api_key_header for passado (ex.: WAHA X-Api-Key), usa no request.
    """
    if not url or not str(cliente_id).strip():
        return None
    cliente_id = str(cliente_id).strip()
    ext = _ext_from_mime_or_name(mimetype, filename)
    safe_ext = "".join(c for c in ext if c.isalnum() or c in "._-")[:20] or "bin"
    name = f"{cliente_id}_{uuid.uuid4().hex}.{safe_ext}"
    path_dir = _uploads_dir()
    path_file = os.path.join(path_dir, name)

    headers = {}
    if api_key_header:
        headers["X-Api-Key"] = api_key_header

    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        with open(path_file, "wb") as f:
            f.write(r.content)
        return f"/api/anexo/{name}"
    except Exception:
        try:
            if os.path.isfile(path_file):
                os.remove(path_file)
        except OSError:
            pass
        return None


def save_uploaded_file(file_storage, cliente_id: str) -> tuple[str | None, str | None, str, str]:
    """
    Salva arquivo enviado pelo painel (multipart) em uploads/mensagens.
    file_storage: objeto tipo FileStorage (request.files["file"]).
    Retorna (anexo_url, path_completo, mimetype, nome_original).
    anexo_url = None em caso de erro.
    """
    if not file_storage or not file_storage.filename or not str(cliente_id).strip():
        return (None, None, "", "")
    cliente_id = str(cliente_id).strip()
    nome_original = (file_storage.filename or "").strip() or "arquivo"
    mimetype = (getattr(file_storage, "content_type") or "").strip() or "application/octet-stream"
    ext = _ext_from_mime_or_name(mimetype, nome_original)
    safe_ext = "".join(c for c in ext if c.isalnum() or c in "._-")[:20] or "bin"
    name = f"{cliente_id}_{uuid.uuid4().hex}.{safe_ext}"
    path_dir = _uploads_dir()
    path_file = os.path.join(path_dir, name)
    try:
        file_storage.save(path_file)
        return (f"/api/anexo/{name}", path_file, mimetype, nome_original)
    except Exception:
        try:
            if os.path.isfile(path_file):
                os.remove(path_file)
        except OSError:
            pass
        return (None, None, mimetype, nome_original)


def nome_original_anexo(filename: str, mimetype: str = "") -> str:
    """Nome amigável para exibir (arquivos vindos do WAHA podem ter filename no payload)."""
    if filename and filename.strip():
        return filename.strip()
    ext = _ext_from_mime_or_name(mimetype, "")
    return f"arquivo.{ext}"


def servir_anexo(filename: str, current_user_id: str) -> tuple:
    """
    Serve o arquivo se o dono for current_user_id.
    filename deve ser no formato {cliente_id}_{uuid}.ext (gerado por download_and_save_anexo).
    Retorna (response, status_code) para o Flask.
    """
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return {"erro": "Nome inválido"}, 400
    parts = filename.split("_", 1)
    if len(parts) < 2:
        return {"erro": "Nome inválido"}, 400
    owner_id = parts[0]
    if str(current_user_id) != str(owner_id):
        return {"erro": "Acesso negado"}, 403
    path_dir = _uploads_dir()
    path_file = os.path.join(path_dir, filename)
    if not os.path.isfile(path_file):
        return {"erro": "Arquivo não encontrado"}, 404
    return send_from_directory(path_dir, filename, as_attachment=True, download_name=filename), 200
