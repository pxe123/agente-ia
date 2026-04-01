# Conecta no servidor Oracle e roda inspecao basica (disco, memoria, servico agente-ia).
# Uso: .\inspecionar-servidor.ps1
# Requer: porta 22 acessivel (Test-NetConnection 168.138.149.129 -Port 22 = True)

$chave = "C:\Users\Ricardo De Tomasi\Documents\app\ssh-key-2026-02-05.key"
if (Test-Path "$PSScriptRoot\..\ssh-key-2026-02-05.key") { $chave = "$PSScriptRoot\..\ssh-key-2026-02-05.key" }
$servidor = "ubuntu@168.138.149.129"
$sshOpts = "-o StrictHostKeyChecking=no -o ConnectTimeout=15"

$script = 'echo "=== 1. Disco (df -h) ==="; df -h; echo ""; echo "=== 2. Memoria (free -h) ==="; free -h; echo ""; echo "=== 3. Servico agente-ia ==="; sudo systemctl is-active agente-ia 2>/dev/null || echo "(servico nao encontrado)"; sudo systemctl status agente-ia --no-pager -l 2>/dev/null | head -15; echo ""; echo "=== 4. Ultimas 20 linhas do log (agente-ia) ==="; sudo journalctl -u agente-ia -n 20 --no-pager 2>/dev/null || echo "(sem log)"; echo ""; echo "=== 5. Portas em escuta (80, 443, 5000, 8000) ==="; sudo ss -tlnp 2>/dev/null | grep -E ":(80|443|5000|8000)\s" || echo "(nenhuma)"; echo ""; echo "=== 6. Carga (top 5 processos) ==="; ps aux --sort=-%cpu | head -6'

Write-Host "Conectando e inspecionando servidor..." -ForegroundColor Cyan
ssh -i "$chave" $sshOpts.Split() $servidor $script
if ($LASTEXITCODE -ne 0) {
    Write-Host "Falha na conexao SSH. Verifique: Test-NetConnection -ComputerName 168.138.149.129 -Port 22" -ForegroundColor Red
    exit 1
}
Write-Host "`nInspecao concluida." -ForegroundColor Green
