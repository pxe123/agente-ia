#!/usr/bin/env python3
"""
Gera chaves VAPID para Web Push. Adicione no .env:

  VAPID_PUBLIC_KEY=<chave pública>
  VAPID_PRIVATE_KEY=<chave privada>

Requer: pip install py-vapid e arquivos private_key.pem e public_key.pem
na pasta do projeto (crie com: vapid --gen).
"""
import os
import subprocess

def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base)
    priv_pem = os.path.join(base, "private_key.pem")
    pub_pem = os.path.join(base, "public_key.pem")

    if not os.path.isfile(priv_pem) or not os.path.isfile(pub_pem):
        print("Arquivos private_key.pem e public_key.pem nao encontrados.")
        print("Rode na pasta do projeto: vapid --gen")
        return

    # Chave publica no formato para o navegador (applicationServerKey)
    try:
        out = subprocess.run(
            ["vapid", "--applicationServerKey"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=base,
        )
        raw = (out.stdout or "").strip() if out.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print("Erro ao rodar vapid --applicationServerKey:", e)
        print("Confira se 'vapid' esta no PATH (pip install py-vapid).")
        return
    # vapid --applicationServerKey pode retornar "Application Server Key = BNxxx..."
    pub = raw.replace("Application Server Key = ", "").strip()

    if not pub:
        print("vapid --applicationServerKey nao retornou a chave publica.")
        return

    # Chave privada: conteudo do PEM (para .env use caminho no servidor ou o texto abaixo)
    with open(priv_pem, "r", encoding="utf-8") as f:
        priv_content = f.read().strip()

    # No .env a chave privada pode ser o caminho no servidor (ex: /home/ubuntu/agente-ia/private_key.pem)
    # ou o conteudo com quebras de linha como \n
    priv_one_line = priv_content.replace("\r\n", "\n").replace("\n", "\\n")

    print("Adicione ao seu .env (no servidor):\n")
    print("VAPID_PUBLIC_KEY=" + pub)
    print("VAPID_PRIVATE_KEY=" + priv_one_line)
    print("\nOu, no servidor, copie private_key.pem e public_key.pem e use:")
    print("VAPID_PRIVATE_KEY=/home/ubuntu/agente-ia/private_key.pem")
    print("(e mantenha VAPID_PUBLIC_KEY como acima)")

if __name__ == "__main__":
    main()
