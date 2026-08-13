"""Interfaz de escritorio Scanner — OCR, versiones, rotación y zoom."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QAction, QFont, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from config_loader import get_paths, load_config
from scanner.servicios.aprendizaje_servicio import (
    aprendizaje_habilitado,
    leer_ocr_crudo,
    leer_ocr_crudo_libro,
    registrar_correccion,
)
from scanner.servicios.imagen_servicio import rotar_imagen
from scanner.servicios.latex_servicio import LatexError, generar_tex
from scanner.servicios.ocr_servicio import ocr_a_texto_procesado, unir_paginas
from scanner.servicios.pdf_servicio import contar_paginas, renderizar_pagina
from scanner.servicios.proyecto_servicio import (
    carpeta_proyecto,
    documento_desde_ruta_procesada,
    guardar_ocr_pagina,
    ruta_ocr_pagina,
    ruta_reescrito,
)
from scanner.ui.dialogo_guardar import DialogoGuardarVersion
from scanner.ui.panel_latex import PanelLatex

EXTENSIONES_IMG = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
EXTENSIONES_DOC = EXTENSIONES_IMG | {".pdf"}
ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 0.15


class VistaZoom(QScrollArea):
    """Scroll + zoom con Ctrl+rueda."""

    zoom_solicitado = Signal(float)  # delta relativo (+/-)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("scrollVista")
        self.label = QLabel("Sin documento")
        self.label.setObjectName("vista")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(200, 200)
        self.setWidget(self.label)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_solicitado.emit(ZOOM_STEP)
            elif delta < 0:
                self.zoom_solicitado.emit(-ZOOM_STEP)
            event.accept()
            return
        super().wheelEvent(event)


class PantallaCarga(QDialog):
    def __init__(self, parent=None, titulo: str = "Procesando…"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setFixedSize(420, 140)
        self.setStyleSheet(
            """
            QDialog { background: #1a1f24; color: #e8e4dc; }
            QLabel { color: #e8e4dc; font-size: 13px; }
            QLabel#tituloCarga { font-size: 15px; font-weight: 700; color: #f4f1ea; }
            QProgressBar {
                border: 1px solid #2a323a;
                border-radius: 6px;
                background: #0f1317;
                text-align: center;
                color: #f4f1ea;
                height: 22px;
            }
            QProgressBar::chunk { background: #2c5f4a; border-radius: 5px; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.lbl_titulo = QLabel(titulo)
        self.lbl_titulo.setObjectName("tituloCarga")
        self.lbl_detalle = QLabel("Preparando…")
        self.lbl_detalle.setWordWrap(True)
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        layout.addWidget(self.lbl_titulo)
        layout.addWidget(self.lbl_detalle)
        layout.addWidget(self.barra)

    def configurar(self, titulo: str, detalle: str = "", total: int = 0) -> None:
        self.setWindowTitle(titulo)
        self.lbl_titulo.setText(titulo)
        self.lbl_detalle.setText(detalle or "Preparando…")
        if total > 0:
            self.barra.setRange(0, total)
            self.barra.setValue(0)
            self.barra.setFormat("%v / %m")
        else:
            self.barra.setRange(0, 0)
            self.barra.setFormat("")

    def actualizar(self, actual: int, total: int, mensaje: str) -> None:
        if total > 0:
            if self.barra.maximum() != total:
                self.barra.setRange(0, total)
                self.barra.setFormat("%v / %m")
            self.barra.setValue(min(actual, total))
        self.lbl_detalle.setText(mensaje)
        QApplication.processEvents()


class OcrPaginaWorker(QThread):
    terminado = Signal(int, str, str)  # indice, raw, procesado
    error = Signal(str)

    def __init__(self, ruta_imagen: Path, indice: int):
        super().__init__()
        self.ruta_imagen = ruta_imagen
        self.indice = indice

    def run(self) -> None:
        try:
            raw, proc = ocr_a_texto_procesado(self.ruta_imagen)
            self.terminado.emit(self.indice, raw, proc)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class OcrLibroWorker(QThread):
    progreso = Signal(int, int, str)
    terminado = Signal(list)  # list[(raw, procesado)]
    error = Signal(str)

    def __init__(self, pdf_path: Path):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self) -> None:
        try:
            from scanner.servicios.ocr_servicio import ocr_pdf

            textos = ocr_pdf(
                self.pdf_path,
                callback_progreso=lambda a, b, m: self.progreso.emit(a, b, m),
            )
            self.terminado.emit(textos)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class AbrirPdfWorker(QThread):
    terminado = Signal(int, object)
    error = Signal(str)

    def __init__(self, pdf_path: Path):
        super().__init__()
        self.pdf_path = pdf_path

    def run(self) -> None:
        try:
            total = contar_paginas(self.pdf_path)
            imagen = renderizar_pagina(self.pdf_path, 0)
            self.terminado.emit(total, imagen)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class VentanaScanner(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.rutas = get_paths(self.cfg)
        self.rutas["entrada"].mkdir(parents=True, exist_ok=True)
        self.rutas["salida"].mkdir(parents=True, exist_ok=True)

        self.documento: Path | None = None
        self.proyecto_dir: Path | None = None
        self.es_pdf = False
        self.total_paginas = 1
        self.pagina_actual = 0
        self.imagen_pagina: Path | None = None
        self.pixmap_original: QPixmap | None = None
        self.textos_paginas: list[str] = [""]
        self._silenciar_editor = False
        self.worker: QThread | None = None
        self.carga: PantallaCarga | None = None
        self.zoom = 1.0
        self.modo_ajustar = True
        self.texto_fuente_path: Path | None = None

        self.setWindowTitle("Scanner — Escaneo y reescritura")
        self.resize(1180, 720)
        self.setMinimumSize(900, 560)

        self._aplicar_estilo()
        self._construir_ui()
        self._actualizar_nav()
        self._estado("Listo. Abre un PDF o una imagen escaneada.")

    def _aplicar_estilo(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#central { background: #1a1f24; color: #e8e4dc; }
            QToolBar {
                background: #12161a; border: none; border-bottom: 1px solid #2a323a;
                spacing: 8px; padding: 8px 12px;
            }
            QToolBar QToolButton, QPushButton {
                background: #2c5f4a; color: #f4f1ea; border: none;
                border-radius: 6px; padding: 8px 14px; font-weight: 600;
            }
            QToolBar QToolButton:hover, QPushButton:hover { background: #36785c; }
            QToolBar QToolButton:disabled, QPushButton:disabled {
                background: #3a434c; color: #9aa3ab;
            }
            QPushButton#secundario { background: #2a323a; }
            QPushButton#secundario:hover { background: #3a434c; }
            QLabel#marca {
                color: #f4f1ea; font-size: 18px; font-weight: 700;
                letter-spacing: 0.5px; padding-right: 12px;
            }
            QLabel#tituloPanel, QLabel#paginaInfo, QLabel#zoomInfo {
                color: #a8b0b8; font-size: 11px; font-weight: 600; letter-spacing: 1.2px;
            }
            QLabel#vista {
                background: #0f1317; color: #6b7580;
            }
            QScrollArea#scrollVista {
                background: #0f1317; border: 1px solid #2a323a; border-radius: 8px;
            }
            QTextEdit {
                background: #f7f3ea; color: #1c1915; border: 1px solid #2a323a;
                border-radius: 8px; padding: 14px;
                selection-background-color: #2c5f4a; selection-color: #ffffff;
            }
            QStatusBar { background: #12161a; color: #a8b0b8; border-top: 1px solid #2a323a; }
            QFrame#panel { background: transparent; }
            QTabWidget::pane {
                border: none; background: #1a1f24;
            }
            QTabBar::tab {
                background: #12161a; color: #a8b0b8;
                padding: 10px 18px; margin-right: 2px;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #2c5f4a; color: #f4f1ea; font-weight: 700;
            }
            """
        )

    def _construir_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        barra = QToolBar()
        barra.setMovable(False)
        barra.setIconSize(QSize(16, 16))
        self.addToolBar(barra)

        marca = QLabel("Scanner")
        marca.setObjectName("marca")
        barra.addWidget(marca)

        self.act_abrir = QAction("Abrir", self)
        self.act_abrir.triggered.connect(self.abrir_archivo)
        barra.addAction(self.act_abrir)

        self.act_abrir_texto = QAction("Abrir texto", self)
        self.act_abrir_texto.triggered.connect(self.abrir_texto_procesado)
        barra.addAction(self.act_abrir_texto)

        self.act_ocr = QAction("OCR página", self)
        self.act_ocr.triggered.connect(self.ejecutar_ocr_pagina)
        self.act_ocr.setEnabled(False)
        barra.addAction(self.act_ocr)

        self.act_ocr_libro = QAction("OCR libro", self)
        self.act_ocr_libro.triggered.connect(self.ejecutar_ocr_libro)
        self.act_ocr_libro.setEnabled(False)
        barra.addAction(self.act_ocr_libro)

        self.act_guardar_pagina = QAction("Guardar página", self)
        self.act_guardar_pagina.triggered.connect(self.guardar_pagina)
        self.act_guardar_pagina.setEnabled(False)
        barra.addAction(self.act_guardar_pagina)

        self.act_guardar_libro = QAction("Guardar libro", self)
        self.act_guardar_libro.triggered.connect(self.guardar_libro)
        self.act_guardar_libro.setEnabled(False)
        barra.addAction(self.act_guardar_libro)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        # --- Pestaña Escanear ---
        cuerpo = QWidget()
        cuerpo_layout = QHBoxLayout(cuerpo)
        cuerpo_layout.setContentsMargins(16, 16, 16, 16)
        cuerpo_layout.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        panel_izq = QFrame()
        panel_izq.setObjectName("panel")
        izq = QVBoxLayout(panel_izq)
        izq.setContentsMargins(0, 0, 0, 0)

        titulo_img = QLabel("PÁGINA ESCANEADA")
        titulo_img.setObjectName("tituloPanel")
        izq.addWidget(titulo_img)

        self.scroll_vista = VistaZoom()
        self.scroll_vista.setMinimumWidth(360)
        self.scroll_vista.zoom_solicitado.connect(self._zoom_delta)
        self.vista = self.scroll_vista.label
        izq.addWidget(self.scroll_vista, stretch=1)

        zoom_fila = QHBoxLayout()
        self.btn_zoom_menos = QPushButton("−")
        self.btn_zoom_menos.setObjectName("secundario")
        self.btn_zoom_menos.clicked.connect(lambda: self._zoom_delta(-ZOOM_STEP))
        self.btn_zoom_mas = QPushButton("+")
        self.btn_zoom_mas.setObjectName("secundario")
        self.btn_zoom_mas.clicked.connect(lambda: self._zoom_delta(ZOOM_STEP))
        self.btn_zoom_fit = QPushButton("Ajustar")
        self.btn_zoom_fit.setObjectName("secundario")
        self.btn_zoom_fit.clicked.connect(self._zoom_ajustar)
        self.lbl_zoom = QLabel("Zoom 100%")
        self.lbl_zoom.setObjectName("zoomInfo")
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_fila.addWidget(self.btn_zoom_menos)
        zoom_fila.addWidget(self.btn_zoom_mas)
        zoom_fila.addWidget(self.btn_zoom_fit)
        zoom_fila.addWidget(self.lbl_zoom, stretch=1)
        izq.addLayout(zoom_fila)

        rot_fila = QHBoxLayout()
        self.btn_rot_izq = QPushButton("⟲ 90°")
        self.btn_rot_izq.setObjectName("secundario")
        self.btn_rot_izq.clicked.connect(lambda: self._rotar(90))
        self.btn_rot_der = QPushButton("⟳ 90°")
        self.btn_rot_der.setObjectName("secundario")
        self.btn_rot_der.clicked.connect(lambda: self._rotar(-90))
        self.btn_rot_180 = QPushButton("180°")
        self.btn_rot_180.setObjectName("secundario")
        self.btn_rot_180.clicked.connect(lambda: self._rotar(180))
        for b in (self.btn_rot_izq, self.btn_rot_der, self.btn_rot_180):
            b.setEnabled(False)
            rot_fila.addWidget(b)
        izq.addLayout(rot_fila)

        nav = QHBoxLayout()
        self.btn_ant = QPushButton("← Anterior")
        self.btn_ant.setObjectName("secundario")
        self.btn_ant.clicked.connect(self.pagina_anterior)
        self.lbl_pagina = QLabel("Página —/—")
        self.lbl_pagina.setObjectName("paginaInfo")
        self.lbl_pagina.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_sig = QPushButton("Siguiente →")
        self.btn_sig.setObjectName("secundario")
        self.btn_sig.clicked.connect(self.pagina_siguiente)
        nav.addWidget(self.btn_ant)
        nav.addWidget(self.lbl_pagina, stretch=1)
        nav.addWidget(self.btn_sig)
        izq.addLayout(nav)

        btn_fila = QHBoxLayout()
        btn_abrir = QPushButton("Elegir archivo…")
        btn_abrir.setObjectName("secundario")
        btn_abrir.clicked.connect(self.abrir_archivo)
        btn_entrada = QPushButton("Desde entrada/")
        btn_entrada.setObjectName("secundario")
        btn_entrada.clicked.connect(self.abrir_desde_entrada)
        btn_fila.addWidget(btn_abrir)
        btn_fila.addWidget(btn_entrada)
        izq.addLayout(btn_fila)

        panel_der = QFrame()
        panel_der.setObjectName("panel")
        der = QVBoxLayout(panel_der)
        der.setContentsMargins(0, 0, 0, 0)
        titulo_txt = QLabel("TEXTO EDITABLE (REESCRITURA)")
        titulo_txt.setObjectName("tituloPanel")
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "El texto reconocido aparecerá aquí.\n"
            "Puedes corregirlo y reescribirlo antes de guardar."
        )
        self.editor.setFont(QFont("Georgia", 12))
        self.editor.textChanged.connect(self._al_cambiar_texto)
        der.addWidget(titulo_txt)
        der.addWidget(self.editor, stretch=1)

        splitter.addWidget(panel_izq)
        splitter.addWidget(panel_der)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        cuerpo_layout.addWidget(splitter)
        self.tabs.addTab(cuerpo, "Escanear")

        # --- Pestaña LaTeX ---
        self.panel_latex = PanelLatex()
        self.panel_latex.estado.connect(self._estado)
        self.panel_latex.ocupado.connect(self._ocupado)
        self.panel_latex.configurar_sync(self._sincronizar_latex_desde_editor)
        self.tabs.addTab(self.panel_latex, "LaTeX")
        self.tabs.currentChanged.connect(self._al_cambiar_pestana)

        self.setStatusBar(QStatusBar())

    def _estado(self, mensaje: str) -> None:
        self.statusBar().showMessage(mensaje)

    def _mostrar_carga(self, titulo: str, detalle: str = "", total: int = 0) -> None:
        if self.carga is None:
            self.carga = PantallaCarga(self, titulo)
        self.carga.configurar(titulo, detalle, total)
        self.carga.show()
        QApplication.processEvents()

    def _ocultar_carga(self) -> None:
        if self.carga is not None:
            self.carga.hide()

    def _ocupado(self, activo: bool) -> None:
        libre = not activo
        self.act_abrir.setEnabled(libre)
        self.act_abrir_texto.setEnabled(libre)
        self.act_ocr.setEnabled(libre and self.imagen_pagina is not None)
        self.act_ocr_libro.setEnabled(libre and self.es_pdf and self.documento is not None)
        self.btn_ant.setEnabled(libre and self.pagina_actual > 0)
        self.btn_sig.setEnabled(libre and self.pagina_actual < self.total_paginas - 1)
        hay_img = libre and self.imagen_pagina is not None
        for b in (self.btn_rot_izq, self.btn_rot_der, self.btn_rot_180):
            b.setEnabled(hay_img)
        self._actualizar_guardar()

    def _actualizar_guardar(self) -> None:
        hay_texto_pagina = bool(self.editor.toPlainText().strip())
        hay_texto_libro = any(t.strip() for t in self.textos_paginas)
        self.act_guardar_pagina.setEnabled(hay_texto_pagina and self.documento is not None)
        self.act_guardar_libro.setEnabled(hay_texto_libro and self.documento is not None)

    def _guardar_tex_version(self, nombre: str, version: int, texto: str) -> Path | None:
        try:
            tex = generar_tex(self.documento, nombre, version, texto)
            return tex
        except LatexError as exc:
            QMessageBox.warning(
                self,
                "LaTeX",
                f"Se guardó el texto, pero falló generar .tex:\n{exc}",
            )
            return None
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "LaTeX",
                f"Se guardó el texto, pero falló generar .tex:\n{exc}",
            )
            return None

    def _texto_completo_trabajo(self) -> str:
        self._guardar_editor_en_memoria()
        if len(self.textos_paginas) > 1 and any(
            t.strip() for i, t in enumerate(self.textos_paginas) if i != self.pagina_actual
        ):
            return unir_paginas(self.textos_paginas)
        return self.editor.toPlainText()

    def _sincronizar_latex_desde_editor(self, *, forzar: bool = False, compilar: bool = True) -> None:
        if not self.documento:
            return
        texto = self._texto_completo_trabajo()
        if not texto.strip():
            self._estado("No hay texto para generar LaTeX.")
            return
        nombre, version = "trabajo", 1
        if self.texto_fuente_path:
            from scanner.servicios.proyecto_servicio import parse_stem_version
            parsed = parse_stem_version(self.texto_fuente_path)
            if parsed:
                nombre, version = parsed
            else:
                nombre = self.texto_fuente_path.stem
        tex = self.panel_latex.sincronizar_desde_texto(
            texto, nombre=nombre, version=version, forzar=forzar
        )
        if tex and compilar:
            self.panel_latex.compilar()

    def _al_cambiar_pestana(self, indice: int) -> None:
        if indice == 1 and self.documento and self.panel_latex.tex_path is None:
            self._sincronizar_latex_desde_editor(forzar=True, compilar=True)

    def abrir_texto_procesado(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        inicio = str(self.rutas["salida"])
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir texto procesado",
            inicio,
            "Textos (*.txt);;Todos (*.*)",
        )
        if not ruta:
            return
        txt = Path(ruta)
        try:
            documento = documento_desde_ruta_procesada(txt)
        except ValueError:
            documento = Path(f"/scanner/documentos/{txt.stem}.pdf")
        contenido = txt.read_text(encoding="utf-8")
        self.documento = documento
        self.proyecto_dir = carpeta_proyecto(documento)
        self.texto_fuente_path = txt
        self.es_pdf = documento.suffix.lower() == ".pdf" and documento.is_file()
        self.total_paginas = 1
        self.pagina_actual = 0
        self.textos_paginas = [contenido]
        self.imagen_pagina = None
        self.pixmap_original = None
        self.vista.setText(f"Texto: {txt.name}\n(sin vista de imagen)")
        self.vista.setPixmap(QPixmap())
        self._mostrar_texto_pagina()
        self._actualizar_nav()
        self.act_ocr.setEnabled(False)
        self.act_ocr_libro.setEnabled(False)
        for b in (self.btn_rot_izq, self.btn_rot_der, self.btn_rot_180):
            b.setEnabled(False)
        self.panel_latex.set_documento(documento)
        self._sincronizar_latex_desde_editor(forzar=True, compilar=False)
        self.tabs.setCurrentIndex(1)
        self.panel_latex.compilar()
        self._estado(f"Texto abierto: {txt.name} → LaTeX en proyecto {self.proyecto_dir.name}")

    def _al_cambiar_texto(self) -> None:
        if self._silenciar_editor:
            return
        if 0 <= self.pagina_actual < len(self.textos_paginas):
            self.textos_paginas[self.pagina_actual] = self.editor.toPlainText()
        self._actualizar_guardar()

    def _guardar_editor_en_memoria(self) -> None:
        if 0 <= self.pagina_actual < len(self.textos_paginas):
            self.textos_paginas[self.pagina_actual] = self.editor.toPlainText()

    def _mostrar_texto_pagina(self) -> None:
        self._silenciar_editor = True
        texto = ""
        if 0 <= self.pagina_actual < len(self.textos_paginas):
            texto = self.textos_paginas[self.pagina_actual]
        self.editor.setPlainText(texto)
        self._silenciar_editor = False
        self._actualizar_guardar()

    def _actualizar_nav(self) -> None:
        if self.documento is None:
            self.lbl_pagina.setText("Página —/—")
            self.btn_ant.setEnabled(False)
            self.btn_sig.setEnabled(False)
            return
        self.lbl_pagina.setText(f"Página {self.pagina_actual + 1}/{self.total_paginas}")
        self.btn_ant.setEnabled(self.pagina_actual > 0)
        self.btn_sig.setEnabled(self.pagina_actual < self.total_paginas - 1)

    def _actualizar_lbl_zoom(self) -> None:
        if self.modo_ajustar:
            self.lbl_zoom.setText("Zoom: ajustar")
        else:
            self.lbl_zoom.setText(f"Zoom {int(self.zoom * 100)}%")

    def _zoom_delta(self, delta: float) -> None:
        if self.pixmap_original is None or self.pixmap_original.isNull():
            return
        if self.modo_ajustar:
            # Partir del factor fit actual
            self.modo_ajustar = False
            self.zoom = self._factor_fit()
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom + delta))
        self._aplicar_zoom()

    def _zoom_ajustar(self) -> None:
        self.modo_ajustar = True
        self._aplicar_zoom()

    def _factor_fit(self) -> float:
        if self.pixmap_original is None or self.pixmap_original.isNull():
            return 1.0
        area = self.scroll_vista.viewport().size()
        if area.width() < 20 or area.height() < 20:
            area = QSize(400, 520)
        pw, ph = self.pixmap_original.width(), self.pixmap_original.height()
        if pw <= 0 or ph <= 0:
            return 1.0
        return min(area.width() / pw, area.height() / ph)

    def _aplicar_zoom(self) -> None:
        if self.pixmap_original is None or self.pixmap_original.isNull():
            self.vista.setText("Sin documento")
            self.vista.setPixmap(QPixmap())
            self._actualizar_lbl_zoom()
            return
        if self.modo_ajustar:
            factor = self._factor_fit()
            self.zoom = factor
        else:
            factor = self.zoom
        w = max(1, int(self.pixmap_original.width() * factor))
        h = max(1, int(self.pixmap_original.height() * factor))
        escalada = self.pixmap_original.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.vista.setPixmap(escalada)
        self.vista.resize(escalada.size())
        self._actualizar_lbl_zoom()

    def abrir_archivo(self) -> None:
        inicio = str(self.rutas["entrada"])
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir escaneo",
            inicio,
            "Documentos (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
            "PDF (*.pdf);;Imágenes (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
        )
        if ruta:
            self._cargar_documento(Path(ruta))

    def abrir_desde_entrada(self) -> None:
        carpeta = self.rutas["entrada"]
        candidatos = sorted(
            p
            for p in carpeta.iterdir()
            if p.is_file() and p.suffix.lower() in EXTENSIONES_DOC
        )
        if not candidatos:
            QMessageBox.information(
                self, "Sin archivos", f"No hay PDF/imágenes en:\n{carpeta}"
            )
            return
        pdfs = [p for p in candidatos if p.suffix.lower() == ".pdf"]
        self._cargar_documento(pdfs[0] if pdfs else candidatos[0])

    def _cargar_documento(self, ruta: Path) -> None:
        if not ruta.is_file():
            QMessageBox.warning(self, "Error", f"No existe el archivo:\n{ruta}")
            return
        if self.worker and self.worker.isRunning():
            return

        self._guardar_editor_en_memoria()
        self.documento = ruta
        self.es_pdf = ruta.suffix.lower() == ".pdf"
        self.pagina_actual = 0
        self.proyecto_dir = carpeta_proyecto(ruta)
        self.modo_ajustar = True

        if self.es_pdf:
            self._ocupado(True)
            self._mostrar_carga(
                "Abriendo PDF",
                f"Creando carpeta del libro y renderizando página 1…\n{self.proyecto_dir}",
                0,
            )
            self.worker = AbrirPdfWorker(ruta)
            self.worker.terminado.connect(self._abrir_pdf_ok)
            self.worker.error.connect(self._abrir_pdf_error)
            self.worker.finished.connect(self._fin_abrir)
            self.worker.start()
            return

        self.total_paginas = 1
        self.textos_paginas = [""]
        self.imagen_pagina = ruta
        self._mostrar_imagen_actual()
        self._mostrar_texto_pagina()
        self._actualizar_nav()
        self.act_ocr.setEnabled(True)
        self.act_ocr_libro.setEnabled(False)
        self.texto_fuente_path = None
        self.panel_latex.set_documento(ruta)
        self._ocupado(False)
        self._estado(f"Documento: {ruta.name} → {self.proyecto_dir}")

    def _abrir_pdf_ok(self, total: int, imagen: object) -> None:
        self.total_paginas = total
        self.textos_paginas = [""] * total
        self.imagen_pagina = Path(imagen)
        self.modo_ajustar = True
        self._mostrar_imagen_actual()
        self._mostrar_texto_pagina()
        self._actualizar_nav()
        self.act_ocr.setEnabled(True)
        self.act_ocr_libro.setEnabled(True)
        self.texto_fuente_path = None
        self.panel_latex.set_documento(self.documento)
        self._estado(
            f"Documento: {self.documento.name} ({total} pág.) → {self.proyecto_dir}"
        )

    def _abrir_pdf_error(self, mensaje: str) -> None:
        QMessageBox.critical(self, "Error al abrir", mensaje)
        self.documento = None
        self.proyecto_dir = None
        self.imagen_pagina = None
        self.pixmap_original = None
        self._estado("Error al abrir el PDF.")

    def _fin_abrir(self) -> None:
        self._ocultar_carga()
        self._ocupado(False)

    def _mostrar_imagen_actual(self) -> None:
        if not self.imagen_pagina or not self.imagen_pagina.is_file():
            self.pixmap_original = None
            self.vista.setText("Sin imagen")
            self.vista.setPixmap(QPixmap())
            return
        pixmap = QPixmap(str(self.imagen_pagina))
        if pixmap.isNull():
            self.pixmap_original = None
            self.vista.setText("No se pudo cargar la imagen")
            return
        self.pixmap_original = pixmap
        self._aplicar_zoom()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.modo_ajustar and self.pixmap_original is not None:
            self._aplicar_zoom()

    def _rotar(self, grados: int) -> None:
        if not self.imagen_pagina or not self.imagen_pagina.is_file():
            return
        try:
            rotar_imagen(self.imagen_pagina, grados)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error al rotar", str(exc))
            return
        self.modo_ajustar = True
        self._mostrar_imagen_actual()
        aviso = "Página rotada."
        if 0 <= self.pagina_actual < len(self.textos_paginas) and self.textos_paginas[
            self.pagina_actual
        ].strip():
            aviso += " Conviene volver a ejecutar OCR."
        self._estado(aviso)

    def pagina_anterior(self) -> None:
        if self.pagina_actual <= 0:
            return
        self._ir_a_pagina(self.pagina_actual - 1)

    def pagina_siguiente(self) -> None:
        if self.pagina_actual >= self.total_paginas - 1:
            return
        self._ir_a_pagina(self.pagina_actual + 1)

    def _ir_a_pagina(self, indice: int) -> None:
        if self.documento is None:
            return
        self._guardar_editor_en_memoria()
        self.pagina_actual = indice
        self.modo_ajustar = True
        try:
            if self.es_pdf:
                self._mostrar_carga(
                    "Cargando página",
                    f"Página {indice + 1}/{self.total_paginas}…",
                    0,
                )
                QApplication.processEvents()
                self.imagen_pagina = renderizar_pagina(self.documento, indice)
                self._ocultar_carga()
            else:
                self.imagen_pagina = self.documento
        except Exception as exc:  # noqa: BLE001
            self._ocultar_carga()
            QMessageBox.warning(self, "Error", str(exc))
            return
        self._mostrar_imagen_actual()
        self._mostrar_texto_pagina()
        self._actualizar_nav()
        self._estado(f"Página {indice + 1}/{self.total_paginas}")

    def ejecutar_ocr_pagina(self) -> None:
        if not self.imagen_pagina:
            return
        if self.worker and self.worker.isRunning():
            return
        self._ocupado(True)
        self._mostrar_carga(
            "OCR en curso",
            f"Procesando página {self.pagina_actual + 1}/{self.total_paginas}…\n"
            "La primera vez puede descargar modelos.",
            0,
        )
        self._estado(f"OCR página {self.pagina_actual + 1}/{self.total_paginas}…")
        self.worker = OcrPaginaWorker(self.imagen_pagina, self.pagina_actual)
        self.worker.terminado.connect(self._ocr_pagina_ok)
        self.worker.error.connect(self._ocr_error)
        self.worker.finished.connect(self._fin_ocr)
        self.worker.start()

    def _ocr_pagina_ok(self, indice: int, raw: str, procesado: str) -> None:
        if indice < len(self.textos_paginas):
            self.textos_paginas[indice] = procesado
        if self.documento:
            guardar_ocr_pagina(self.documento, indice, raw, procesado)
        if indice == self.pagina_actual:
            self._mostrar_texto_pagina()
        self._estado(f"OCR página {indice + 1} completado.")

    def ejecutar_ocr_libro(self) -> None:
        if not self.es_pdf or not self.documento:
            QMessageBox.information(self, "Solo PDF", "«OCR libro» requiere un PDF abierto.")
            return
        if self.worker and self.worker.isRunning():
            return
        resp = QMessageBox.question(
            self,
            "OCR libro completo",
            f"Se procesarán {self.total_paginas} páginas en CPU.\n"
            f"Resultados en:\n{self.proyecto_dir}\n\n¿Continuar?",
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._guardar_editor_en_memoria()
        self._ocupado(True)
        self._mostrar_carga("OCR libro completo", "Iniciando…", self.total_paginas)
        self._estado("OCR libro: iniciando…")
        self.worker = OcrLibroWorker(self.documento)
        self.worker.progreso.connect(self._ocr_libro_progreso)
        self.worker.terminado.connect(self._ocr_libro_ok)
        self.worker.error.connect(self._ocr_error)
        self.worker.finished.connect(self._fin_ocr)
        self.worker.start()

    def _ocr_libro_progreso(self, actual: int, total: int, mensaje: str) -> None:
        if self.carga:
            self.carga.actualizar(actual, total, mensaje)
        self._estado(f"{mensaje} ({actual}/{total})")

    def _ocr_libro_ok(self, pares: list) -> None:
        raws: list[str] = []
        procs: list[str] = []
        for item in pares:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                raws.append(str(item[0] or ""))
                procs.append(str(item[1] or ""))
            else:
                t = str(item or "")
                raws.append(t)
                procs.append(t)
        self.textos_paginas = list(procs)
        if len(self.textos_paginas) < self.total_paginas:
            self.textos_paginas.extend([""] * (self.total_paginas - len(self.textos_paginas)))
            raws.extend([""] * (self.total_paginas - len(raws)))
        if self.documento:
            for i, (raw, proc) in enumerate(zip(raws, self.textos_paginas)):
                guardar_ocr_pagina(self.documento, i, raw, proc)
            ruta_reescrito(self.documento).write_text(
                unir_paginas(self.textos_paginas), encoding="utf-8"
            )
        self._mostrar_texto_pagina()
        self._estado(f"OCR libro completado. Carpeta: {self.proyecto_dir}")

    def _ocr_error(self, mensaje: str) -> None:
        QMessageBox.critical(self, "Error en OCR", mensaje)
        self._estado("Error al procesar.")

    def _fin_ocr(self) -> None:
        self._ocultar_carga()
        self._ocupado(False)

    def _aprender_de_pagina(self, indice: int, corregido: str) -> str | None:
        if not self.documento or not aprendizaje_habilitado(self.cfg):
            return None
        bruto = leer_ocr_crudo(self.documento, indice)
        if bruto is None:
            return "Sin .raw.txt: vuelve a pasar OCR para aprender de esta página."
        info = registrar_correccion(
            bruto,
            corregido,
            documento=self.documento,
            pagina=indice + 1,
            fuente="guardar_pagina",
        )
        if not info.get("registrado"):
            return None
        return (
            f"Aprendizaje: {info.get('pares_extraidos', 0)} sustituciones "
            f"({info.get('reglas', 0)} reglas activas)."
        )

    def _aprender_de_libro(self, corregido: str) -> str | None:
        if not self.documento or not aprendizaje_habilitado(self.cfg):
            return None
        bruto = leer_ocr_crudo_libro(self.documento, self.total_paginas)
        if bruto is None:
            return "Sin .raw.txt: vuelve a pasar OCR libro para aprender."
        info = registrar_correccion(
            bruto,
            corregido,
            documento=self.documento,
            pagina=None,
            fuente="guardar_libro",
        )
        if not info.get("registrado"):
            return None
        return (
            f"Aprendizaje: {info.get('pares_extraidos', 0)} sustituciones "
            f"({info.get('reglas', 0)} reglas activas)."
        )

    def guardar_pagina(self) -> None:
        self._guardar_editor_en_memoria()
        texto = self.editor.toPlainText().strip()
        if not texto or not self.documento:
            return
        sugerido = f"pagina_{self.pagina_actual + 1:03d}"
        dlg = DialogoGuardarVersion(
            self, self.documento, sugerido, titulo="Guardar versión de página"
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nombre, version, destino, aprender = dlg.resultado()
        if destino.exists():
            resp = QMessageBox.question(
                self,
                "Sobrescribir",
                f"Ya existe:\n{destino.name}\n¿Sobrescribir?",
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        destino.write_text(texto + "\n", encoding="utf-8")
        # Borrador editable (no tocar .raw.txt)
        ruta_ocr_pagina(self.documento, self.pagina_actual).write_text(
            texto + "\n", encoding="utf-8"
        )
        nota_apr = None
        if aprender:
            nota_apr = self._aprender_de_pagina(self.pagina_actual, texto)
        tex = self._guardar_tex_version(nombre, version, texto)
        msg = f"Página guardada en:\n{destino}"
        if nota_apr:
            msg += f"\n\n{nota_apr}"
        if tex:
            msg += f"\n\nLaTeX:\n{tex}"
            self.texto_fuente_path = destino
            self.panel_latex.cargar_tex_archivo(tex)
        self._estado(f"Versión guardada: {nombre}_v{version}")
        QMessageBox.information(self, "Guardado", msg)

    def guardar_libro(self) -> None:
        self._guardar_editor_en_memoria()
        if not self.documento or not any(t.strip() for t in self.textos_paginas):
            return
        dlg = DialogoGuardarVersion(
            self, self.documento, "libro_completo", titulo="Guardar versión del libro"
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        nombre, version, destino, aprender = dlg.resultado()
        if destino.exists():
            resp = QMessageBox.question(
                self,
                "Sobrescribir",
                f"Ya existe:\n{destino.name}\n¿Sobrescribir?",
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        contenido = unir_paginas(self.textos_paginas)
        destino.write_text(contenido, encoding="utf-8")
        for i, texto in enumerate(self.textos_paginas):
            if texto.strip():
                ruta_ocr_pagina(self.documento, i).write_text(
                    texto + "\n", encoding="utf-8"
                )
        ruta_reescrito(self.documento).write_text(contenido, encoding="utf-8")
        nota_apr = None
        if aprender:
            nota_apr = self._aprender_de_libro(contenido)
        tex = self._guardar_tex_version(nombre, version, contenido)
        msg = f"Libro guardado en:\n{destino}"
        if nota_apr:
            msg += f"\n\n{nota_apr}"
        if tex:
            msg += f"\n\nLaTeX:\n{tex}"
            self.texto_fuente_path = destino
            self.panel_latex.cargar_tex_archivo(tex)
        self._estado(f"Libro guardado: {nombre}_v{version}")
        QMessageBox.information(self, "Guardado", msg)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Scanner")
    app.setOrganizationName("Soviets")
    ventana = VentanaScanner()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
