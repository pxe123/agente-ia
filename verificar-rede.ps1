# Verificacao rapida da rede local - execute no PowerShell
# Uso: .\verificar-rede.ps1

Write-Host "`n=== 1. Gateway (roteador) ===" -ForegroundColor Cyan
$gw = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty NextHop
if ($gw) {
    Write-Host "Gateway: $gw" -ForegroundColor Green
    $pingGw = Test-Connection -ComputerName $gw -Count 1 -Quiet -ErrorAction SilentlyContinue
    if ($pingGw) { Write-Host "Ping ao roteador: OK" -ForegroundColor Green } else { Write-Host "Ping ao roteador: falhou" -ForegroundColor Yellow }
} else {
    Write-Host "Gateway nao encontrado." -ForegroundColor Red
}

Write-Host "`n=== 2. Seu IP e adaptador ===" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" } | Sort-Object { if ($_.IPAddress.StartsWith("169.254")) { 1 } else { 0 } }, InterfaceAlias | ForEach-Object {
    $ip = $_.IPAddress
    $note = ""
    if ($ip.StartsWith("169.254")) { $note = " (link-local: sem DHCP?)" }
    Write-Host "  $($_.InterfaceAlias): $ip$note" -ForegroundColor $(if ($note) { "Yellow" } else { "White" })
}

Write-Host "`n=== 3. DNS (resolucao de nomes) ===" -ForegroundColor Cyan
$dns = Resolve-DnsName -Name "google.com" -ErrorAction SilentlyContinue
if ($dns) { Write-Host "DNS (google.com): OK" -ForegroundColor Green } else { Write-Host "DNS: falhou" -ForegroundColor Red }

Write-Host "`n=== 4. Internet (conectividade) ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "https://www.google.com" -UseBasicParsing -TimeoutSec 5
    Write-Host "Acesso a internet (HTTPS): OK" -ForegroundColor Green
} catch {
    Write-Host "Acesso a internet: falhou ou lento" -ForegroundColor Yellow
}

Write-Host "`n=== 5. Porta 22 (SSH) para seu servidor ===" -ForegroundColor Cyan
$server = "168.138.149.129"
$tcp = Test-NetConnection -ComputerName $server -Port 22 -WarningAction SilentlyContinue
if ($tcp.TcpTestSucceeded) {
    Write-Host "SSH (porta 22) para $server : OK" -ForegroundColor Green
} else {
    Write-Host "SSH (porta 22) para $server : falhou (timeout ou bloqueado)" -ForegroundColor Red
}

Write-Host "`n=== 6. Resumo de rotas (primeiras linhas) ===" -ForegroundColor Cyan
Get-NetRoute -AddressFamily IPv4 | Where-Object { $_.DestinationPrefix -ne "127.0.0.0/8" } | Select-Object -First 8 | Format-Table DestinationPrefix, NextHop, InterfaceAlias -AutoSize

Write-Host "`nConcluido." -ForegroundColor Cyan
