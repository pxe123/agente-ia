# Corrige permissões no servidor para o usuário ubuntu poder fazer scp/rsync.
# Execute na raiz do projeto: .\scripts\fix-server-permissions.ps1
# (Ajuste $key e $host se precisar.)

# Chave em app (fora do repo agente-ia) para maior seguranca
$key = Join-Path $PSScriptRoot "..\..\ssh-key-2026-02-05.key"
$sshHost = "ubuntu@168.138.149.129"

Write-Host "Ajustando dono de ~/agente-ia para ubuntu no servidor..."
ssh -i $key $sshHost "sudo chown -R ubuntu:ubuntu ~/agente-ia"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Permissoes corrigidas. Pode rodar o scp novamente."
} else {
    Write-Host "Falha. Verifique a chave SSH e o acesso ao servidor."
}
