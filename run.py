"""Punto de entrada de Atlas.

Ejecutar desde la carpeta del proyecto:

    python run.py

También funciona como módulo:

    python -m atlas.app
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite lanzarlo desde cualquier directorio, no solo desde la raíz del proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft  # noqa: E402

from atlas.app import main  # noqa: E402


if __name__ == "__main__":
    ft.run(main)
