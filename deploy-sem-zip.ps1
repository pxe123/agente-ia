# Deploy sem zip: copia os arquivos da pasta direto para o servidor (igual ao jeito antigo).
# Execute na pasta do projeto: cd "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia"

$ErrorActionPreference = "Stop"
$origem = "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia"
$pasta  = "C:\Users\Ricardo De Tomasi\Documents\agente-ia-temp"
$servidor = "ubuntu@168.138.149.129"

# Chave SSH: preferir app (fora do repo) para maior seguranca
$chaveApp = "C:\Users\Ricardo De Tomasi\Documents\app\ssh-key-2026-02-05.key"
$chaveProjeto = "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia\ssh-key-2026-02-05.key"
$chaveSsh = "C:\Users\Ricardo De Tomasi\.ssh\ssh-key-2026-02-05.key"
$chave = $null
if (Test-Path $chaveApp) { $chave = $chaveApp }
elseif (Test-Path $chaveProjeto) { $chave = $chaveProjeto }
elseif (Test-Path $chaveSsh) { $chave = $chaveSsh }
else {
    Write-Host "Erro: Chave SSH nao encontrada. Coloque em:" -ForegroundColor Red
    Write-Host "  $chaveApp" -ForegroundColor Yellow
    Write-Host "  ou  $chaveSsh" -ForegroundColor Yellow
    exit 1
}

Write-Host "Ajustando permissoes no servidor (dono ubuntu)..." -ForegroundColor Cyan
ssh -i $chave -o StrictHostKeyChecking=no $servidor "sudo chown -R ubuntu:ubuntu ~/agente-ia 2>/dev/null; mkdir -p ~/agente-ia ~/agente-ia-temp"
if ($LASTEXITCODE -ne 0) { Write-Host "Aviso: chown pode ter falhado (sudo). Continuando..." -ForegroundColor Yellow }

Write-Host "Preparando pasta (mesmas exclusoes do zip)..." -ForegroundColor Cyan
if (Test-Path $pasta) { Remove-Item $pasta -Recurse -Force }
New-Item -ItemType Directory -Path $pasta -Force | Out-Null

robocopy $origem $pasta /E /XD __pycache__ .git .cursor .vscode venv .venv /XF *.pyc /NFL /NDL /NJH /NJS /NC /NS | Out-Null
Remove-Item "$pasta\ssh-key-2026-02-05.key" -Force -ErrorAction SilentlyContinue
Remove-Item "$pasta\.env" -Force -ErrorAction SilentlyContinue
Remove-Item "$pasta\DIAGNOSTICO-*.txt" -Force -ErrorAction SilentlyContinue
Remove-Item "$pasta\*.log" -Force -ErrorAction SilentlyContinue


Write-Host "Enviando arquivos (pode demorar)..." -ForegroundColor Cyan
# Envia a pasta temp inteira; no servidor copiamos o conteudo para ~/agente-ia (sobrescreve arquivos, mantem .env que ja esta la)
scp -i $chave -r -o StrictHostKeyChecking=no "$pasta" "${servidor}:~/agente-ia-temp"

Write-Host "Atualizando pasta agente-ia no servidor..." -ForegroundColor Cyan
ssh -i $chave -o StrictHostKeyChecking=no $servidor "sh -c 'cp -r ~/agente-ia-temp/* ~/agente-ia/ 2>/dev/null; rm -rf ~/agente-ia-temp'"

Remove-Item $pasta -Recurse -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Deploy concluido. Arquivos estao em ~/agente-ia no servidor." -ForegroundColor Green
Write-Host "Se precisar reiniciar o app, entre no servidor e rode o comando de restart (ex.: systemctl, pm2 ou o que voce usa)." -ForegroundColor Gray
Write-Host ""
Write-Host "Entrar no servidor: ssh -i `"$chave`" $servidor" -ForegroundColor White
Write-Host ""
