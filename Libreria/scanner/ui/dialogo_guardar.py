"""Diálogo para guardar texto con nombre y número de versión."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from scanner.servicios.proyecto_servicio import (
    ruta_version,
    sanitizar_nombre,
    siguiente_version,
)


class DialogoGuardarVersion(QDialog):
    def __init__(
        self,
        parent,
        documento: Path,
        nombre_sugerido: str,
        titulo: str = "Guardar versión",
        aprender_por_defecto: bool = True,
    ):
        super().__init__(parent)
        self.documento = documento
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(
            """
            QDialog { background: #1a1f24; color: #e8e4dc; }
            QLabel { color: #e8e4dc; }
            QLineEdit, QSpinBox {
                background: #0f1317;
                color: #f4f1ea;
                border: 1px solid #2a323a;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QCheckBox { color: #e8e4dc; spacing: 8px; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 1px solid #2a323a; border-radius: 3px;
                background: #0f1317;
            }
            QCheckBox::indicator:checked { background: #2c5f4a; }
            QLabel#rutaPrev {
                color: #a8b0b8;
                font-size: 11px;
            }
            """
        )

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.nombre = QLineEdit(nombre_sugerido)
        self.version = QSpinBox()
        self.version.setRange(1, 9999)
        self.version.setValue(siguiente_version(documento, nombre_sugerido))
        self.version.setPrefix("v")

        form.addRow("Nombre:", self.nombre)
        form.addRow("Versión:", self.version)
        layout.addLayout(form)

        self.chk_aprender = QCheckBox("Usar como ejemplo de aprendizaje")
        self.chk_aprender.setChecked(aprender_por_defecto)
        self.chk_aprender.setToolTip(
            "Compara tu corrección con el OCR bruto (.raw.txt) y actualiza las reglas."
        )
        layout.addWidget(self.chk_aprender)

        self.ruta_prev = QLabel("")
        self.ruta_prev.setObjectName("rutaPrev")
        self.ruta_prev.setWordWrap(True)
        self.ruta_prev.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.ruta_prev)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self.nombre.textChanged.connect(self._al_cambiar_nombre)
        self.version.valueChanged.connect(self._actualizar_ruta)
        self._actualizar_ruta()

    def _al_cambiar_nombre(self, texto: str) -> None:
        sugerida = siguiente_version(self.documento, texto or "version")
        self.version.blockSignals(True)
        self.version.setValue(sugerida)
        self.version.blockSignals(False)
        self._actualizar_ruta()

    def _actualizar_ruta(self) -> None:
        ruta = self.ruta_destino()
        self.ruta_prev.setText(f"Se guardará en:\n{ruta}")

    def ruta_destino(self) -> Path:
        return ruta_version(
            self.documento,
            sanitizar_nombre(self.nombre.text()),
            self.version.value(),
        )

    def resultado(self) -> tuple[str, int, Path, bool]:
        nombre = sanitizar_nombre(self.nombre.text())
        version = self.version.value()
        return (
            nombre,
            version,
            ruta_version(self.documento, nombre, version),
            self.chk_aprender.isChecked(),
        )
