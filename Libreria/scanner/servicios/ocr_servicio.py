"""Servicio OCR compartido (CLI y escritorio)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from config_loader import load_config

_ocr_engine = None
_ocr_firma: tuple | None = None

ProgresoCb = Callable[[int, int, str], None]


def _params_ocr(cfg: dict | None = None) -> dict:
    ocr = (cfg or load_config()).get("ocr", {})
    params = {
        "lang": ocr.get("idioma", "es"),
        "use_doc_orientation_classify": ocr.get("use_doc_orientation_classify", True),
        "use_doc_unwarping": ocr.get("use_doc_unwarping", True),
        "use_textline_orientation": ocr.get("use_textline_orientation", True),
    }
    # Ajustes finos (español / escaneos antiguos)
    for clave in (
        "text_det_thresh",
        "text_det_box_thresh",
        "text_det_unclip_ratio",
        "text_det_limit_side_len",
        "text_det_limit_type",
        "text_rec_score_thresh",
        "ocr_version",
    ):
        if clave in ocr and ocr[clave] is not None:
            params[clave] = ocr[clave]
    return params


def crear_ocr(cfg: dict | None = None):
    from paddleocr import PaddleOCR

    return PaddleOCR(**_params_ocr(cfg))


def get_ocr():
    """Reutiliza una sola instancia (recarga si cambió la config relevante)."""
    global _ocr_engine, _ocr_firma
    firma = tuple(sorted(_params_ocr().items()))
    if _ocr_engine is None or firma != _ocr_firma:
        _ocr_engine = crear_ocr()
        _ocr_firma = firma
    return _ocr_engine


def ocr_imagen(ruta_imagen: Path, reiniciar: bool = False) -> list[str]:
    global _ocr_engine, _ocr_firma
    if reiniciar:
        _ocr_engine = None
        _ocr_firma = None

    ocr = get_ocr()
    resultado = ocr.predict(str(ruta_imagen))
    lineas: list[str] = []

    for pagina in resultado:
        textos = None
        if hasattr(pagina, "get"):
            textos = pagina.get("rec_texts")
        elif isinstance(pagina, dict):
            textos = pagina.get("rec_texts")
        if textos:
            lineas.extend(str(t) for t in textos)
        else:
            lineas.append(str(pagina))

    return lineas


def ocr_a_texto(ruta_imagen: Path) -> str:
    """OCR bruto (sin postproceso de aprendizaje)."""
    return "\n".join(ocr_imagen(ruta_imagen)).strip()


def ocr_a_texto_procesado(ruta_imagen: Path) -> tuple[str, str]:
    """Devuelve (texto_raw, texto_postprocesado)."""
    from scanner.servicios.aprendizaje_servicio import aplicar_postproceso

    bruto = ocr_a_texto(ruta_imagen)
    return bruto, aplicar_postproceso(bruto)


def ocr_pdf(
    ruta_pdf: Path,
    callback_progreso: ProgresoCb | None = None,
) -> list[tuple[str, str]]:
    """OCR de todas las páginas. Devuelve lista de (raw, procesado)."""
    from scanner.servicios.pdf_servicio import contar_paginas, renderizar_pagina

    total = contar_paginas(ruta_pdf)
    textos: list[tuple[str, str]] = []

    for i in range(total):
        if callback_progreso:
            callback_progreso(i + 1, total, f"Renderizando página {i + 1}/{total}")
        imagen = renderizar_pagina(ruta_pdf, i)
        if callback_progreso:
            callback_progreso(i + 1, total, f"OCR página {i + 1}/{total}")
        textos.append(ocr_a_texto_procesado(imagen))

    if callback_progreso:
        callback_progreso(total, total, "OCR libro completado")
    return textos


def unir_paginas(textos: list[str]) -> str:
    bloques: list[str] = []
    for i, texto in enumerate(textos, start=1):
        cuerpo = (texto or "").strip()
        bloques.append(f"--- Página {i} ---\n{cuerpo}".rstrip())
    return "\n\n".join(bloques) + "\n"
