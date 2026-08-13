"""Pestaña LaTeX: render PDF a la izquierda y código .tex a la derecha."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from scanner.servicios.latex_servicio import (
    LatexError,
    compilar_si_necesario,
    generar_tex,
)
from scanner.servicios.proyecto_servicio import parse_stem_version


class _CompilarWorker(QThread):
    terminado = Signal(object)
    error = Signal(str)

    def __init__(self, documento: Path, tex_path: Path):
        super().__init__()
        self.documento = documento
        self.tex_path = tex_path

    def run(self) -> None:
        try:
            self.terminado.emit(compilar_si_necesario(self.documento, self.tex_path))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class PanelLatex(QWidget):
    estado = Signal(str)
    ocupado = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.documento: Path | None = None
        self.tex_path: Path | None = None
        self._tex_editado_a_mano = False
        self._silenciar = False
        self._worker: _CompilarWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        barra = QHBoxLayout()
        self.lbl_archivo = QLabel("Sin documento LaTeX")
        self.lbl_archivo.setObjectName("tituloPanel")
        barra.addWidget(self.lbl_archivo, stretch=1)

        self.btn_sync = QPushButton("Sincronizar desde texto")
        self.btn_sync.setObjectName("secundario")
        self.btn_compilar = QPushButton("Compilar / Actualizar vista")
        self.btn_guardar = QPushButton("Guardar .tex")
        self.btn_guardar.setObjectName("secundario")
        barra.addWidget(self.btn_sync)
        barra.addWidget(self.btn_guardar)
        barra.addWidget(self.btn_compilar)
        root.addLayout(barra)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        izq = QWidget()
        lizq = QVBoxLayout(izq)
        lizq.setContentsMargins(0, 0, 0, 0)
        cab_pdf = QHBoxLayout()
        cab_pdf.addWidget(QLabel("RENDER (PDF)"))
        cab_pdf.addStretch(1)
        self.btn_ant = QPushButton("◀")
        self.btn_ant.setObjectName("secundario")
        self.btn_ant.setFixedWidth(36)
        self.btn_sig = QPushButton("▶")
        self.btn_sig.setObjectName("secundario")
        self.btn_sig.setFixedWidth(36)
        self.lbl_pagina = QLabel("—")
        cab_pdf.addWidget(self.btn_ant)
        cab_pdf.addWidget(self.lbl_pagina)
        cab_pdf.addWidget(self.btn_sig)
        lizq.addLayout(cab_pdf)

        self.doc_pdf = QPdfDocument(self)
        self.vista = QPdfView(self)
        self.vista.setDocument(self.doc_pdf)
        # Continuas: se puede desplazar por todo el libro (no solo portada)
        self.vista.setPageMode(QPdfView.PageMode.MultiPage)
        self.vista.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        lizq.addWidget(self.vista, stretch=1)

        self.btn_ant.clicked.connect(lambda: self._ir_pagina(-1))
        self.btn_sig.clicked.connect(lambda: self._ir_pagina(1))
        self.doc_pdf.statusChanged.connect(self._actualizar_lbl_pagina)
        nav = self.vista.pageNavigator()
        nav.currentPageChanged.connect(lambda *_: self._actualizar_lbl_pagina())

        der = QWidget()
        lder = QVBoxLayout(der)
        lder.setContentsMargins(0, 0, 0, 0)
        lder.addWidget(QLabel("CÓDIGO LaTeX"))
        self.editor = QPlainTextEdit()
        mono = QFont("DejaVu Sans Mono", 11)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(mono)
        self.editor.setPlaceholderText(
            "Aquí aparece el .tex generado desde tu texto OCR.\n"
            "Puedes editarlo y pulsar Compilar."
        )
        self.editor.setStyleSheet(
            "QPlainTextEdit { background:#0f1317; color:#e8e4dc; border:1px solid #2a323a;"
            " border-radius:8px; padding:10px; }"
        )
        self.editor.textChanged.connect(self._al_editar)
        lder.addWidget(self.editor, stretch=1)

        splitter.addWidget(izq)
        splitter.addWidget(der)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        self.btn_sync.clicked.connect(self._emit_sync_request)
        self.btn_compilar.clicked.connect(self.compilar)
        self.btn_guardar.clicked.connect(self.guardar_tex)

        self._pedir_sync = None  # callback opcional asignado por la app

    def configurar_sync(self, callback) -> None:
        self._pedir_sync = callback

    def _emit_sync_request(self) -> None:
        if self._pedir_sync:
            self._pedir_sync()

    def set_documento(self, documento: Path | None) -> None:
        self.documento = documento
        self.tex_path = None
        self._tex_editado_a_mano = False
        if documento is None:
            self.lbl_archivo.setText("Sin documento LaTeX")
            self._silenciar = True
            self.editor.clear()
            self._silenciar = False
            self.doc_pdf.close()

    def _al_editar(self) -> None:
        if self._silenciar:
            return
        self._tex_editado_a_mano = True

    def cargar_tex_archivo(self, tex_path: Path) -> None:
        self.tex_path = tex_path
        self._silenciar = True
        self.editor.setPlainText(tex_path.read_text(encoding="utf-8"))
        self._silenciar = False
        self._tex_editado_a_mano = False
        self.lbl_archivo.setText(tex_path.name)
        self.estado.emit(f"LaTeX cargado: {tex_path}")

    def sincronizar_desde_texto(
        self,
        texto: str,
        *,
        nombre: str = "trabajo",
        version: int = 1,
        forzar: bool = False,
    ) -> Path | None:
        if not self.documento:
            QMessageBox.information(self, "LaTeX", "Abre un documento o texto primero.")
            return None
        if self._tex_editado_a_mano and not forzar:
            resp = QMessageBox.question(
                self,
                "Sincronizar",
                "Editaste el .tex a mano. ¿Regenerarlo desde el texto OCR?",
            )
            if resp != QMessageBox.StandardButton.Yes:
                return self.tex_path

        # Si ya hay tex_path versionado, reutilizar nombre/versión
        if self.tex_path:
            parsed = parse_stem_version(self.tex_path)
            if parsed:
                nombre, version = parsed

        try:
            tex = generar_tex(self.documento, nombre, version, texto)
        except LatexError as exc:
            QMessageBox.warning(self, "LaTeX", str(exc))
            return None

        self.cargar_tex_archivo(tex)
        return tex

    def guardar_tex(self) -> None:
        if not self.tex_path:
            QMessageBox.information(self, "LaTeX", "No hay archivo .tex aún. Sincroniza primero.")
            return
        self.tex_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        # invalidar hash
        sha = self.tex_path.with_suffix(self.tex_path.suffix + ".sha256")
        if sha.exists():
            sha.unlink()
        self._tex_editado_a_mano = False
        self.estado.emit(f"Guardado: {self.tex_path}")

    def compilar(self) -> None:
        if not self.documento:
            QMessageBox.information(self, "LaTeX", "No hay documento asociado.")
            return
        if not self.tex_path:
            QMessageBox.information(self, "LaTeX", "Sincroniza o genera un .tex primero.")
            return
        if self._worker and self._worker.isRunning():
            return

        # Persistir editor antes de compilar
        self.tex_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        sha = self.tex_path.with_suffix(self.tex_path.suffix + ".sha256")
        if sha.exists():
            sha.unlink()

        self.ocupado.emit(True)
        self.estado.emit(f"Compilando {self.tex_path.name}…")
        self._worker = _CompilarWorker(self.documento, self.tex_path)
        self._worker.terminado.connect(self._ok)
        self._worker.error.connect(self._error)
        self._worker.finished.connect(lambda: self.ocupado.emit(False))
        self._worker.start()

    def _ok(self, pdf: object) -> None:
        ruta = Path(pdf)
        self.doc_pdf.load(str(ruta))
        self._actualizar_lbl_pagina()
        n = self.doc_pdf.pageCount()
        self.estado.emit(f"PDF listo ({n} págs.): {ruta}")

    def _error(self, mensaje: str) -> None:
        QMessageBox.critical(self, "Error LaTeX", mensaje)
        self.estado.emit("Error al compilar LaTeX.")

    def _ir_pagina(self, delta: int) -> None:
        nav = self.vista.pageNavigator()
        total = self.doc_pdf.pageCount()
        if total <= 0:
            return
        dest = max(0, min(total - 1, nav.currentPage() + delta))
        nav.jump(dest, nav.currentLocation(), nav.currentZoom())
        self._actualizar_lbl_pagina()

    def _actualizar_lbl_pagina(self) -> None:
        total = self.doc_pdf.pageCount()
        if total <= 0:
            self.lbl_pagina.setText("—")
            return
        actual = self.vista.pageNavigator().currentPage() + 1
        self.lbl_pagina.setText(f"{actual} / {total}")
