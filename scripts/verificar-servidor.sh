#!/bin/bash
# Verificação do servidor - rode no servidor: ssh -i SUA_CHAVE ubuntu@168.138.149.129
# Depois: bash verificar-servidor.sh   (ou chmod +x e ./verificar-servidor.sh)

echo "========== DISCO =========="
df -h /

echo ""
echo "========== MAIORES PASTAS EM ~ =========="
du -sh ~/* 2>/dev/null | sort -hr | head -15

echo ""
echo "========== PASTA DO PROJETO (~/agente-ia) =========="
if [ -d ~/agente-ia ]; then
    du -sh ~/agente-ia
    echo "Conteúdo (tamanhos):"
    du -sh ~/agente-ia/* 2>/dev/null | sort -hr
else
    echo "Pasta ~/agente-ia não existe."
fi

echo ""
echo "========== LIXO / TEMP =========="
echo "agente-ia-temp (deploy):"
du -sh ~/agente-ia-temp 2>/dev/null || echo "  (não existe - ok)"
echo "Logs em ~/agente-ia:"
find ~/agente-ia -maxdepth 3 -name "*.log" -type f 2>/dev/null | head -20
echo "Arquivos .pyc:"
find ~/agente-ia -name "*.pyc" -type f 2>/dev/null | wc -l

echo ""
echo "========== MEMÓRIA =========="
free -h

echo ""
echo "========== PROCESSOS DO APP (python/node) =========="
ps aux | grep -E "python|node|uvicorn|gunicorn" | grep -v grep

echo ""
echo "========== PORTAS EM USO (80, 443, 5000, 8000) =========="
for p in 80 443 5000 8000; do
    cmd=$(ss -tlnp 2>/dev/null | grep ":$p " || true)
    [ -n "$cmd" ] && echo "Porta $p: $cmd"
done

echo ""
echo "========== SUGESTÕES DE LIMPEZA =========="
echo "Se quiser limpar no servidor (cuidado, revise antes):"
echo "  rm -rf ~/agente-ia-temp          # pasta temp do deploy (pode ter ficado)"
echo "  find ~/agente-ia -name '*.pyc' -delete"
echo "  find ~/agente-ia -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null"
echo "  truncate logs grandes manualmente se houver"
echo ""
echo "Fim da verificação."
