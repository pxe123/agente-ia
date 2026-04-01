# Deploy: envia para pasta temporaria no servidor e depois copia para ~/agente-ia.
# Execute: cd "C:\Users\Ricardo De Tomasi\Documents\app\agente-ia" e depois .\deploy.ps1
# Antes do deploy, se alterou HTML/classes Tailwind: npm run build:css (gera panel/static/css/tailwind.css).
# O script usa "sudo rm -rf ~/agente-ia-upload" no servidor para evitar Permission denied (pasta com dono root).

Set-Location $PSScriptRoot
$chave = "$PSScriptRoot\..\ssh-key-2026-02-05.key"
if (-not (Test-Path $chave)) { $chave = "C:\Users\Ricardo De Tomasi\Documents\app\ssh-key-2026-02-05.key" }
$servidor = "ubuntu@168.138.149.129"
$origem = $PSScriptRoot
$pastaTemp = "$env:TEMP\agente-ia-deploy-upload"
$maxTentativas = 4
$esperaEntreTentativas = 10

$sshOpts = "-o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"

if (-not (Test-Path $chave)) {
    Write-Host "Chave nao encontrada: $chave" -ForegroundColor Red
    exit 1
}

$hostServidor = $servidor -replace '^[^@]+@', ''
Write-Host "Verificando conexao com $hostServidor (porta 22)..." -ForegroundColor Cyan
$test = Test-NetConnection -ComputerName $hostServidor -Port 22 -WarningAction SilentlyContinue
if (-not $test.TcpTestSucceeded) {
    Write-Host "Aviso: Test-NetConnection falhou. Tentando SSH mesmo assim..." -ForegroundColor Yellow
}

function ExecutarComRetry {
    param([string]$nome, [scriptblock]$acao)
    $tentativa = 1
    while ($true) {
        if ($tentativa -gt 1) { Write-Host "  Tentativa $tentativa de $maxTentativas..." -ForegroundColor Yellow }
        & $acao
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($tentativa -ge $maxTentativas) { return $false }
        Write-Host "  Falhou. Nova tentativa em ${esperaEntreTentativas}s..." -ForegroundColor Yellow
        Start-Sleep -Seconds $esperaEntreTentativas
        $tentativa++
    }
}

# 0. Preparar pasta local sem .git, venv, node_modules, etc.
Write-Host "Preparando arquivos (excluindo .git, venv, cache)..." -ForegroundColor Cyan
if (Test-Path $pastaTemp) { Remove-Item $pastaTemp -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $pastaTemp -Force | Out-Null
$robocopyArgs = @($origem, $pastaTemp, "/E", "/XD", "__pycache__", ".git", ".cursor", ".vscode", "venv", ".venv", "node_modules", "/XF", "*.pyc", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS")
& robocopy @robocopyArgs | Out-Null
Remove-Item "$pastaTemp\ssh-key-2026-02-05.key" -Force -ErrorAction SilentlyContinue
Remove-Item "$pastaTemp\.env" -Force -ErrorAction SilentlyContinue
# Nao enviar .env do PC; o servidor mantem o .env dele

# 1. Limpar pasta no servidor (sudo evita Permission denied se restou dono root)
Write-Host "Enviando arquivos por SCP..." -ForegroundColor Cyan
$ok = ExecutarComRetry "preparar-upload" {
    ssh -i "$chave" $sshOpts.Split() $servidor "sudo rm -rf ~/agente-ia-upload; mkdir -p ~/agente-ia-upload"
}
if ($ok) {
    $ok = ExecutarComRetry "scp" {
        scp -i "$chave" -r $sshOpts.Split() "${pastaTemp}\*" "${servidor}:~/agente-ia-upload/"
    }
}
if (Test-Path $pastaTemp) { Remove-Item $pastaTemp -Recurse -Force -ErrorAction SilentlyContinue }
if (-not $ok) {
    Write-Host "Falha no envio. Tente de novo." -ForegroundColor Red
    exit 1
}
Start-Sleep -Seconds 2

# 3. Aplicar no servidor (copiar, dono, limpar temp, reiniciar servico)
Write-Host "Aplicando no servidor (se pedir senha, digite)..." -ForegroundColor Cyan
$cmd = "sudo cp -r ~/agente-ia-upload/* ~/agente-ia/ && sudo chown -R ubuntu:ubuntu ~/agente-ia && sudo rm -rf ~/agente-ia-upload && sudo systemctl restart agente-ia && echo Deploy OK"
$ok = ExecutarComRetry "aplicar" {
    ssh -i "$chave" $sshOpts.Split() $servidor $cmd
}
if ($ok) {
    Write-Host "Deploy concluido." -ForegroundColor Green
} else {
    Write-Host "Falha ao aplicar no servidor. Verifique a senha do sudo ou a conexao." -ForegroundColor Yellow
    exit 1
}
