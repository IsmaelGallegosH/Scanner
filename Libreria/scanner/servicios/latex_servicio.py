"""Generación y compilación LaTeX bajo demanda (caché por hash)."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from config_loader import load_config
from scanner.paths import SISTEMA_ROOT
from scanner.servicios.proyecto_servicio import (
    carpeta_latex_build,
    ruta_version_pdf,
    ruta_version_tex,
    sanitizar_nombre,
)

MARCADOR = "__CONTENIDO__"
_ESCAPE = str.maketrans(
    {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
)


class LatexError(RuntimeError):
    pass


def carpeta_plantillas() -> Path:
    return SISTEMA_ROOT / "plantillas"


def resolver_motor(config: dict | None = None) -> str:
    cfg = (config or load_config()).get("latex", {})
    preferido = str(cfg.get("motor", "auto")).lower()
    if preferido in ("xelatex", "pdflatex"):
        if shutil.which(preferido):
            return preferido
        raise LatexError(
            f"Motor '{preferido}' no encontrado. Instala texlive-xetex / texlive-latex-base."
        )
    if shutil.which("xelatex"):
        return "xelatex"
    if shutil.which("pdflatex"):
        return "pdflatex"
    raise LatexError(
        "No hay motor LaTeX. Instala: sudo apt install texlive-xetex texlive-lang-spanish"
    )


def resolver_plantilla(config: dict | None = None, motor: str | None = None) -> Path:
    cfg = config or load_config()
    latex_cfg = cfg.get("latex", {})
    modo = str(latex_cfg.get("plantilla", "auto")).lower()
    base = carpeta_plantillas()
    motor = motor or "xelatex"

    usuario = base / "libro.tex"
    if modo == "libro" or (modo == "auto" and usuario.is_file()):
        if not usuario.is_file():
            raise LatexError(f"Plantilla de usuario no encontrada: {usuario}")
        return usuario

    if motor == "pdflatex":
        generico_pdf = base / "libro_generico_pdflatex.tex"
        if generico_pdf.is_file():
            return generico_pdf

    generico = base / "libro_generico.tex"
    if not generico.is_file():
        raise LatexError(f"Plantilla genérica no encontrada: {generico}")
    return generico


def escapar_latex(texto: str) -> str:
    return texto.translate(_ESCAPE)


def _lineas_a_parrafos(lineas: list[str]) -> list[str]:
    """Une renglones OCR en párrafos; respeta líneas en blanco."""
    parrafos: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        partes: list[str] = []
        i = 0
        while i < len(buffer):
            trozo = buffer[i].strip()
            # Unir cortes silábicos: "pala-" + "bra" -> "palabra"
            while trozo.endswith("-") and i + 1 < len(buffer):
                i += 1
                trozo = trozo[:-1] + buffer[i].strip()
            partes.append(trozo)
            i += 1
        cuerpo = re.sub(r"\s+", " ", " ".join(partes)).strip()
        if cuerpo:
            parrafos.append(cuerpo)
        buffer = []

    for linea in lineas:
        if not linea.strip():
            flush()
            continue
        buffer.append(linea.strip())
    flush()
    return parrafos


def texto_a_latex(texto: str) -> str:
    """
    Convierte texto OCR/plano a LaTeX de libro legible.
    - Une líneas seguidas en párrafos (el OCR corta a mitad de renglón).
    - Línea vacía = nuevo párrafo.
    - Separadores --- Página N --- = nueva página.
    - Si el mismo número de página aparece más de una vez (p. ej. libro
      duplicado en el .txt), conserva la versión con más texto.
    """
    cuerpos: dict[int, str] = {}
    actual = 0
    bucket: list[str] = []

    def cerrar_bucket() -> None:
        nonlocal bucket, actual
        if actual == 0 and not any(x.strip() for x in bucket):
            bucket = []
            return
        pars = _lineas_a_parrafos(bucket)
        cuerpo = "\n\n".join(pars)
        prev = cuerpos.get(actual, "")
        if len(cuerpo) >= len(prev):
            cuerpos[actual] = cuerpo
        bucket = []

    for cruda in texto.splitlines():
        linea = cruda.rstrip()
        m_pag = re.match(r"^---\s*P[aá]gina\s+(\d+)\s*---\s*$", linea, re.IGNORECASE)
        if m_pag:
            cerrar_bucket()
            actual = int(m_pag.group(1))
            continue
        bucket.append(linea)
    cerrar_bucket()

    lineas_out: list[str] = []
    secuencia: list[int] = []
    if cuerpos.get(0, "").strip():
        secuencia.append(0)
    secuencia.extend(sorted(n for n in cuerpos if n > 0))

    for i, num in enumerate(secuencia):
        cuerpo = cuerpos.get(num, "").strip()
        if not cuerpo:
            continue
        if i > 0:
            lineas_out.append(r"\clearpage")
        if num > 0:
            lineas_out.append(rf"\section*{{Página {num}}}")
            lineas_out.append("")
        for parrafo in cuerpo.split("\n\n"):
            p = parrafo.strip()
            if p:
                lineas_out.append(escapar_latex(p))
                lineas_out.append("")

    return "\n".join(lineas_out).strip() + "\n"


def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1024 * 64), b""):
            h.update(bloque)
    return h.hexdigest()


def generar_tex(
    documento: Path,
    nombre: str,
    version: int,
    texto: str,
    config: dict | None = None,
) -> Path:
    """Escribe el .tex de la versión (sin compilar)."""
    cfg = config or load_config()
    motor = "xelatex"
    try:
        motor = resolver_motor(cfg)
    except LatexError:
        motor = "pdflatex"  # plantilla fallback; compilar fallará después con mensaje claro

    plantilla = resolver_plantilla(cfg, motor=motor)
    crudo = plantilla.read_text(encoding="utf-8")

    titulo = sanitizar_nombre(nombre).replace("_", " ")
    contenido = texto_a_latex(texto)
    cuerpo = crudo.replace("__TITULO__", escapar_latex(titulo), 1)

    # Solo sustituir el marcador como línea completa (evita comentarios)
    lineas_out: list[str] = []
    reemplazado = False
    for linea in cuerpo.splitlines(keepends=True):
        if not reemplazado and linea.strip() == MARCADOR:
            bloque = contenido if contenido.endswith("\n") else contenido + "\n"
            lineas_out.append(bloque)
            reemplazado = True
        else:
            lineas_out.append(linea)
    if not reemplazado:
        raise LatexError(
            f"La plantilla debe tener una línea exacta '{MARCADOR}': {plantilla}"
        )
    cuerpo = "".join(lineas_out)

    destino = ruta_version_tex(documento, nombre, version, cfg)
    destino.write_text(cuerpo, encoding="utf-8")
    sha = destino.with_suffix(destino.suffix + ".sha256")
    if sha.exists():
        sha.unlink()
    return destino


def _hash_sidecar(tex_path: Path) -> Path:
    return tex_path.with_suffix(tex_path.suffix + ".sha256")


def necesita_compilar(tex_path: Path, pdf_path: Path) -> bool:
    if not tex_path.is_file():
        return True
    if not pdf_path.is_file():
        return True
    sidecar = _hash_sidecar(tex_path)
    if not sidecar.is_file():
        return True
    actual = _sha256_archivo(tex_path)
    guardado = sidecar.read_text(encoding="utf-8").strip()
    return actual != guardado


def _parse_stem_version(tex_path: Path) -> tuple[str, int]:
    m = re.match(r"^(?P<nombre>.+)_v(?P<num>\d+)$", tex_path.stem, re.IGNORECASE)
    if not m:
        return tex_path.stem, 1
    return m.group("nombre"), int(m.group("num"))


def compilar_si_necesario(
    documento: Path,
    tex_path: Path,
    config: dict | None = None,
) -> Path:
    """
    Compila el .tex a PDF solo si cambió (hash).
    Devuelve la ruta del PDF en versiones/.
    """
    cfg = config or load_config()
    nombre, version = _parse_stem_version(tex_path)
    pdf_path = ruta_version_pdf(documento, nombre, version, cfg)

    if not necesita_compilar(tex_path, pdf_path):
        return pdf_path

    motor = resolver_motor(cfg)
    timeout = int(cfg.get("latex", {}).get("timeout_seg", 120))
    build = carpeta_latex_build(documento, nombre, version, cfg)

    job = "main"
    fuente_build = build / f"{job}.tex"
    shutil.copy2(tex_path, fuente_build)

    cmd = [
        motor,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={build}",
        str(fuente_build),
    ]

    # Dos pasadas ligeras: título/TOC estable sin costar demasiado
    ultimo = None
    for _ in range(2):
        ultimo = subprocess.run(
            cmd,
            cwd=str(build),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if ultimo.returncode != 0:
            log = build / f"{job}.log"
            detalle = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else (
                ultimo.stderr or ultimo.stdout or "sin salida"
            )
            raise LatexError(f"Falló {motor}:\n{detalle}")

    pdf_build = build / f"{job}.pdf"
    if not pdf_build.is_file():
        raise LatexError(f"No se generó PDF con {motor}.")

    shutil.copy2(pdf_build, pdf_path)
    _hash_sidecar(tex_path).write_text(_sha256_archivo(tex_path), encoding="utf-8")
    return pdf_path


def asegurar_tex_desde_txt(
    documento: Path,
    txt_path: Path,
    config: dict | None = None,
) -> Path:
    """
    Si existe .tex hermano lo usa; si no, lo genera desde el .txt.
    También acepta reescrito.txt / ocr/*.txt creando una versión temporal.
    """
    from scanner.servicios.proyecto_servicio import parse_stem_version, siguiente_version

    cfg = config or load_config()
    texto = txt_path.read_text(encoding="utf-8")

    parsed = parse_stem_version(txt_path)
    if parsed:
        nombre, version = parsed
        tex = ruta_version_tex(documento, nombre, version, cfg)
        if tex.is_file():
            return tex
        return generar_tex(documento, nombre, version, texto, cfg)

    # Texto sin versión (reescrito / ocr): crear versión automática
    nombre = sanitizar_nombre(txt_path.stem) or "procesado"
    version = siguiente_version(documento, nombre, cfg)
    # Guardar también copia versionada del texto para trazabilidad
    from scanner.servicios.proyecto_servicio import ruta_version

    ruta_version(documento, nombre, version, cfg).write_text(texto, encoding="utf-8")
    return generar_tex(documento, nombre, version, texto, cfg)
