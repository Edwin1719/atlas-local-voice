"""Limpieza de texto para respuesta y voz.

El modelo, sobre todo después de usar una herramienta, responde con listas,
negritas, tablas y enlaces. En pantalla es ruido; leído en voz alta, inservible.

La limpieza no depende del prompt: es una garantía del código. Se aplica al texto
que se muestra, al que se guarda en el historial y al que se sintetiza.
"""
from __future__ import annotations

import re

_CERCA_DE_CODIGO = re.compile(r"```[a-zA-Z0-9]*\n?(.*?)```", re.DOTALL)
_BLOQUE_CODIGO = re.compile(r"```")
_IMAGEN = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_ENLACE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_ENLACE_DESNUDO = re.compile(r"\(\s*https?://[^)]*\)")
_URL = re.compile(r"https?://\S+")
_SEPARADOR_TABLA = re.compile(r"^\s*\|?[\s:|-]{3,}\|?\s*$", re.MULTILINE)
_BARRAS = re.compile(r"\s*\|\s*")
_SIMBOLOS = re.compile(r"[*_`#>~]+")
_VINETA = re.compile(r"^\s*[-•▪◦‣·]\s*", re.MULTILINE)
_NUMERADA = re.compile(r"^\s*\d+[.)]\s*", re.MULTILINE)
_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # pictogramas y símbolos
    "\U00002600-\U000027BF"  # miscelánea y dingbats
    "\U0001F1E6-\U0001F1FF"  # banderas
    "\u2190-\u21FF"          # flechas
    "\u25A0-\u25FF"          # formas geométricas
    "\uFE0F\u200D\u20E3"     # selectores y uniones
    "\u200B-\u200F\uFEFF"    # invisibles
    "]",
)
_PARENTESIS_VACIO = re.compile(r"\(\s*\)|\[\s*\]")
_ESPACIO_ANTES_SIGNO = re.compile(r"\s+([,.;:!?])")
_SIGNOS_REPETIDOS = re.compile(r"([,.;:!?])\1{2,}")
_ESPACIOS = re.compile(r"[ \t]{2,}")
_SALTOS = re.compile(r"\n{3,}")


def to_speech_text(texto: str) -> str:
    """Devuelve el texto limpio: sin markdown, sin emojis y sin URLs."""
    if not texto:
        return ""
    limpio = _CERCA_DE_CODIGO.sub(r"\1", texto)   # deja el contenido del bloque
    limpio = _BLOQUE_CODIGO.sub("", limpio)
    limpio = _IMAGEN.sub("", limpio)
    limpio = _ENLACE.sub(r"\1", limpio)          # [texto](url) -> texto
    limpio = _ENLACE_DESNUDO.sub("", limpio)     # (https://...) entero
    limpio = _URL.sub("", limpio)
    limpio = _SEPARADOR_TABLA.sub("", limpio)
    limpio = _BARRAS.sub(" ", limpio)
    limpio = _SIMBOLOS.sub("", limpio)
    limpio = _VINETA.sub("", limpio)
    limpio = _NUMERADA.sub("", limpio)
    limpio = _EMOJI.sub("", limpio)
    limpio = _PARENTESIS_VACIO.sub("", limpio)
    limpio = _ESPACIO_ANTES_SIGNO.sub(r"\1", limpio)
    limpio = _SIGNOS_REPETIDOS.sub(r"\1", limpio)
    limpio = _ESPACIOS.sub(" ", limpio)
    limpio = _SALTOS.sub("\n\n", limpio)
    limpio = "\n".join(linea.strip() for linea in limpio.split("\n"))
    return limpio.strip()
