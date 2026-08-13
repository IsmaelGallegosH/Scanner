"""CLI: OCR de una imagen de página."""

from __future__ import annotations

import argparse
from pathlib import Path

from scanner.paths import bootstrap

bootstrap()

from config_loader import get_paths  # noqa: E402
from scanner.servicios.ocr_servicio import ocr_a_texto_procesado  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR de una imagen de página de libro")
    parser.add_argument(
        "imagen",
        nargs="?",
        help="Ruta a la imagen. Si se omite, usa Libreria/entrada/",
    )
    args = parser.parse_args()

    rutas = get_paths()
    rutas["entrada"].mkdir(parents=True, exist_ok=True)
    rutas["salida"].mkdir(parents=True, exist_ok=True)

    if args.imagen:
        imagen = Path(args.imagen).expanduser().resolve()
    else:
        candidatos = sorted(
            p
            for p in rutas["entrada"].iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
        )
        if not candidatos:
            print(f"No hay imágenes en {rutas['entrada']}")
            return 1
        imagen = candidatos[0]

    if not imagen.is_file():
        print(f"No existe: {imagen}")
        return 1

    print(f"Procesando: {imagen}")
    raw, texto = ocr_a_texto_procesado(imagen)
    salida = rutas["salida"] / f"{imagen.stem}_ocr.txt"
    # Preferir proyecto si el stem coincide con un libro
    proyecto = rutas["salida"] / imagen.stem
    if proyecto.is_dir():
        ocr_dir = proyecto / "ocr"
        ocr_dir.mkdir(parents=True, exist_ok=True)
        (ocr_dir / f"{imagen.stem}_ocr.raw.txt").write_text(raw + "\n", encoding="utf-8")
        salida = ocr_dir / f"{imagen.stem}_ocr.txt"
    salida.write_text(texto + "\n", encoding="utf-8")
    print(f"Guardado: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
