"""Utilidades de imagen (rotación de páginas renderizadas)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def rotar_imagen(ruta: Path, grados: int) -> Path:
    """
    Rota la imagen y la sobrescribe.
    grados: 90 (antihorario), -90 / 270 (horario), 180.
    """
    grados = int(grados) % 360
    if grados == 0:
        return ruta

    # Pillow: rotate es antihorario; expand conserva dimensiones
    with Image.open(ruta) as img:
        # convert para no perder modo al guardar PNG
        convertido = img.convert("RGB") if img.mode not in ("RGB", "RGBA", "L") else img
        rotada = convertido.rotate(grados, expand=True)
        rotada.save(ruta)

    return ruta
