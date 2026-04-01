# services/site_analyzer.py
"""
Análise do site da empresa para preencher automaticamente os Campos de Ouro.
Busca o conteúdo público da URL, extrai texto e usa IA para obter nome, sobre, produtos e tom.
"""

import json
import logging
import re
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)

# Limite de caracteres do texto da página enviado à IA (evita token excessivo)
MAX_TEXTO_PAGINA = 15000
REQUEST_TIMEOUT_SEC = 10
USER_AGENT = "Mozilla/5.0 (compatible; SiteAnalyzer/1.0; +https://agente-ia)"


def _strip_html(html: str) -> str:
    """Remove tags HTML e normaliza espaços."""
    if not html or not isinstance(html, str):
        return ""
    # Remove script e style
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Normaliza espaços e quebras
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_url_text(url: str) -> str:
    """
    Acessa a URL e retorna o texto visível da página (sem HTML).
    Respeita timeout e limita o tamanho para uso na IA.
    Tenta https primeiro; se falhar com erro de conexão/SSL, tenta http.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    last_error = None
    urls_to_try = [url]
    if url.startswith("https://"):
        urls_to_try.append(url.replace("https://", "http://", 1))
    elif url.startswith("http://"):
        urls_to_try.append(url.replace("http://", "https://", 1))
    for attempt_url in urls_to_try:
        try:
            r = requests.get(
                attempt_url,
                timeout=REQUEST_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            text = _strip_html(r.text)
            if len(text) > MAX_TEXTO_PAGINA:
                text = text[:MAX_TEXTO_PAGINA] + "…"
            return text
        except requests.RequestException as e:
            last_error = e
            logger.warning("site_analyzer: falha ao buscar %s: %s", attempt_url, e)
    raise ValueError(f"Não foi possível acessar o site: {last_error}") from last_error


def _get_openai_client():
    """Cliente OpenAI (reutiliza lógica do agent_engine)."""
    try:
        from base.config import settings
        key = (getattr(settings, "OPENAI_API_KEY", None) or "").strip()
        if not key:
            return None
        from openai import OpenAI
        return OpenAI(api_key=key)
    except Exception:
        return None


PROMPT_EXTRACAO = """Você recebeu o texto extraído da página (inicial ou principal) do site de uma empresa.
Extraia as informações abaixo e responda APENAS com um JSON válido, sem markdown e sem texto antes ou depois.

Formato do JSON (use exatamente estas chaves):
{"nome_empresa": "...", "descricao_empresa": "...", "produtos_servicos": "...", "personalidade": "...", "tom_voz": "...", "segmento_mercado": "...", "diferencial_competitivo": "...", "horario_funcionamento": "...", "objetivo_atendimento": "..."}

Regras por campo:
- nome_empresa: nome da empresa ou marca (uma frase curta).
- descricao_empresa: o que a empresa faz, em 1 ou 2 frases (sobre a empresa).
- produtos_servicos: principais produtos ou serviços (tópicos ou parágrafo curto).
- personalidade: tom de comunicação da marca (ex.: "Amigável e profissional", "Formal e técnico"). Uma frase curta.
- tom_voz: formal, amigável, técnico, descontraído etc. Uma ou duas palavras. Vazio se não der para inferir.
- segmento_mercado: público ou setor (ex.: "B2B", "varejo", "serviços para PME"). Vazio se não aparecer.
- diferencial_competitivo: o que diferencia a empresa (frase curta ou tópicos). Vazio se não aparecer.
- horario_funcionamento: dias e horários de atendimento, se estiver no texto (ex.: "Segunda a Sexta, 9h às 18h"). Muito comum no rodapé ou em "Contato". Vazio se não encontrar.
- objetivo_atendimento: objetivo principal do contato/atendimento sugerido pelo site (ex.: "Tirar dúvidas, enviar orçamento", "Agendar visita"). Inferir do CTA ou da oferta. Vazio se não der.

Se alguma informação não estiver no texto, use string vazia "" para esse campo. Não invente dados."""


CAMPOS_EXTRACAO = [
    "nome_empresa", "descricao_empresa", "produtos_servicos", "personalidade",
    "tom_voz", "segmento_mercado", "diferencial_competitivo",
    "horario_funcionamento", "objetivo_atendimento",
]


def _empty_campos() -> Dict[str, str]:
    return {k: "" for k in CAMPOS_EXTRACAO}


def extract_campos_ia(texto_pagina: str) -> Dict[str, str]:
    """
    Envia o texto da página para a IA e retorna um dict com todos os campos
    (nome_empresa, descricao_empresa, produtos_servicos, personalidade, tom_voz,
     segmento_mercado, diferencial_competitivo, horario_funcionamento, objetivo_atendimento).
    """
    if not texto_pagina or len(texto_pagina.strip()) < 50:
        return _empty_campos()
    client = _get_openai_client()
    if not client:
        raise ValueError("OpenAI não configurada (OPENAI_API_KEY). Não é possível analisar o site.")
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PROMPT_EXTRACAO},
                {"role": "user", "content": f"Texto do site:\n\n{texto_pagina[:12000]}"},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        content = (completion.choices[0].message.content or "").strip()
        if not content:
            return _empty_campos()
        # Tenta extrair JSON do conteúdo (pode vir com markdown)
        for raw in (content, re.sub(r"^```(?:json)?\s*", "", content), content.split("```")[0]):
            raw = re.sub(r"```\s*$", "", raw).strip()
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    out = _empty_campos()
                    for key in CAMPOS_EXTRACAO:
                        val = data.get(key)
                        if val is not None and str(val).strip():
                            out[key] = str(val).strip()
                    return out
            except json.JSONDecodeError:
                continue
        return _empty_campos()
    except Exception as e:
        logger.warning("site_analyzer: falha na IA: %s", e)
        raise ValueError(f"Erro ao analisar o conteúdo do site: {e}") from e


def analisar_site(url: str) -> Dict[str, str]:
    """
    Busca o site pela URL, extrai texto e usa IA para preencher os campos.
    Retorna dict com nome_empresa, descricao_empresa, produtos_servicos, personalidade.
    """
    texto = fetch_url_text(url)
    return extract_campos_ia(texto)
