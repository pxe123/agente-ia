# panel/routes/legal.py
"""Páginas legais exigidas pela Meta: Política de Privacidade, Termos de Uso, Exclusão de Dados."""
from flask import Blueprint, render_template

legal_bp = Blueprint(
    "legal",
    __name__,
    template_folder="../templates",
)


@legal_bp.route("/politica")
def politica():
    """Política de Privacidade - URL pública para o app da Meta."""
    return render_template("politica.html")


@legal_bp.route("/termos")
def termos():
    """Termos de Uso - URL pública para o app da Meta."""
    return render_template("termos.html")


@legal_bp.route("/exclusao-de-dados")
def exclusao_de_dados():
    """Instruções de exclusão de dados - URL pública exigida pela Meta."""
    return render_template("exclusao_de_dados.html")
