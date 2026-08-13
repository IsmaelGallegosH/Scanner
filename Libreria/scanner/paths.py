"""Raíces del proyecto Scanner (sin hardcodear rutas de imports)."""

from __future__ import annotations

import sys
from pathlib import Path

# Libreria/scanner/paths.py → Libreria/
LIBRERIA_ROOT = Path(__file__).resolve().parents[1]
PROYECTO_ROOT = LIBRERIA_ROOT.parent
SISTEMA_ROOT = PROYECTO_ROOT / "Sistema"


def bootstrap() -> None:
    """Asegura que Sistema y Libreria estén en sys.path una sola vez."""
    for ruta in (str(LIBRERIA_ROOT), str(SISTEMA_ROOT)):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)
