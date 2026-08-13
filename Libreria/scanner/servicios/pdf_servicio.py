"""Renderizado de PDF a imágenes (caché en carpeta del proyecto)."""

from __future__ import annotations

from pathlib import Path

from config_loader import load_config
from scanner.servicios.proyecto_servicio import carpeta_paginas


def get_dpi(config: dict | None = None) -> int:
    cfg = config or load_config()
    return int(cfg.get("pdf", {}).get("dpi", 250))


def get_cache_dir(pdf_path: Path, config: dict | None = None) -> Path:
    """Páginas renderizadas: salida/<nombre>/paginas/"""
    return carpeta_paginas(pdf_path, config)


def contar_paginas(pdf_path: Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def ruta_pagina_cache(pdf_path: Path, indice: int, config: dict | None = None) -> Path:
    """índice base 0 → pagina_001.png"""
    carpeta = get_cache_dir(pdf_path, config)
    return carpeta / f"pagina_{indice + 1:03d}.png"


def renderizar_pagina(
    pdf_path: Path,
    indice: int,
    *,
    dpi: int | None = None,
    forzar: bool = False,
    config: dict | None = None,
) -> Path:
    """Renderiza una página a PNG (usa caché si existe). índice base 0."""
    cfg = config or load_config()
    dpi_eff = dpi if dpi is not None else get_dpi(cfg)
    salida = ruta_pagina_cache(pdf_path, indice, cfg)

    if salida.is_file() and not forzar:
        return salida

    import pypdfium2 as pdfium

    scale = dpi_eff / 72.0
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        if indice < 0 or indice >= len(doc):
            raise IndexError(f"Página fuera de rango: {indice + 1} (total {len(doc)})")
        pagina = doc[indice]
        bitmap = pagina.render(scale=scale)
        pil = bitmap.to_pil()
        salida.parent.mkdir(parents=True, exist_ok=True)
        pil.save(salida, format="PNG")
    finally:
        doc.close()

    return salida


def renderizar_todas(
    pdf_path: Path,
    *,
    dpi: int | None = None,
    forzar: bool = False,
    callback_progreso=None,
    config: dict | None = None,
) -> list[Path]:
    """Renderiza todas las páginas; devuelve rutas PNG en orden."""
    total = contar_paginas(pdf_path)
    rutas: list[Path] = []
    for i in range(total):
        ruta = renderizar_pagina(
            pdf_path, i, dpi=dpi, forzar=forzar, config=config
        )
        rutas.append(ruta)
        if callback_progreso:
            callback_progreso(i + 1, total, ruta)
    return rutas
