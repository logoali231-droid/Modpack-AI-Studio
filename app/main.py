import sys
import shutil
import subprocess
from pathlib import Path
from datetime import timedelta

import requests
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QPushButton, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QTabWidget, QScrollArea
)
from PySide6.QtCore import QThread, Signal, QTimer, QElapsedTimer, Qt, QPointF\nfrom PySide6.QtGui import QPainter, QColor, QPolygonF, QPen
import keyring
from .mod_database import ModDatabase
from .orchestrator import ModpackPipeline

SERVICE = "modpack-ai-studio"

APP_STYLE = """
QMainWindow, QWidget { background: #111827; color: #e5e7eb; font-size: 13px; }
QLabel#appTitle { color: #f9fafb; font-size: 25px; font-weight: 800; }
QLabel#subtitle { color: #9ca3af; font-size: 12px; }
QLabel#sectionTitle { color: #f3f4f6; font-size: 15px; font-weight: 700; }
QLabel#stageLabel { color: #d1d5db; font-size: 13px; font-weight: 600; }
QLabel#elapsedLabel { color: #9ca3af; font-size: 12px; }
QGroupBox {
  background: #1f2937; border: 1px solid #374151; border-radius: 10px;
  margin-top: 12px; padding: 14px; font-weight: 700; color: #f3f4f6;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLineEdit, QComboBox, QTextEdit {
  background: #0b1220; color: #e5e7eb; border: 1px solid #374151;
  border-radius: 7px; padding: 8px; selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid #60a5fa; }
QPushButton {
  background: #2563eb; color: white; border: 0; border-radius: 8px;
  padding: 9px 14px; font-weight: 700;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #374151; color: #9ca3af; }
QPushButton#secondaryButton { background: #374151; color: #e5e7eb; }
QPushButton#secondaryButton:hover { background: #4b5563; }
QTabWidget::pane { border: 1px solid #374151; border-radius: 8px; top: -1px; }
QTabBar::tab { background: #1f2937; color: #9ca3af; padding: 10px 18px; margin-right: 4px;
  border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #263449; color: #f9fafb; }
QProgressBar {
  background: #0b1220; border: 1px solid #374151; border-radius: 6px;
  height: 13px; text-align: center; color: #e5e7eb;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
QCheckBox { spacing: 8px; color: #d1d5db; }
QCheckBox::indicator { width: 16px; height: 16px; }
QStatusBar { color: #9ca3af; }
"""

class StructurePreview(QWidget):
    """Small interactive isometric voxel preview; drag to rotate, wheel to zoom."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setMinimumWidth(420)
        self.setMouseTracking(True)
        self.blocks = []
        self.angle = 0.65
        self.zoom = 1.0
        self._drag_pos = None
        self.setToolTip("Drag to rotate the structure. Use the mouse wheel to zoom.")

    def set_blocks(self, blocks):
        self.blocks = blocks or []
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            pos = event.position().toPoint()
            self.angle += (pos.x() - self._drag_pos.x()) * 0.012
            self._drag_pos = pos
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def wheelEvent(self, event):
        self.zoom = max(0.35, min(3.0, self.zoom * (1.12 if event.angleDelta().y() > 0 else 0.89)))
        self.update()

    @staticmethod
    def _color(block_id):
        palette = {
            "stone": QColor("#89939f"), "wood": QColor("#a8794c"),
            "glass": QColor("#77b9d1"), "leaves": QColor("#56875a"),
            "water": QColor("#477fc0"), "iron": QColor("#aeb8c2"),
            "gold": QColor("#d2ad4d"), "brick": QColor("#a66b59"),
            "lantern": QColor("#e5bd62"), "chest": QColor("#b78345"),
        }
        key = block_id.split(":")[-1]
        for hint, color in palette.items():
            if hint in key:
                return color
        return QColor("#89939f")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b1220"))
        if not self.blocks:
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "3D preview will appear here\\nDrag to rotate · scroll to zoom")
            return
        import math
        cos_a, sin_a = math.cos(self.angle), math.sin(self.angle)
        projected = []
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for item in self.blocks:
            x, y, z, block_id = item
            rx, rz = x * cos_a - z * sin_a, x * sin_a + z * cos_a
            px = (rx - rz) * 0.8660254
            py = (rx + rz) * 0.5 - y
            projected.append((rx + rz + y * 0.01, px, py, self._color(block_id)))
            min_x, max_x = min(min_x, px), max(max_x, px)
            min_y, max_y = min(min_y, py), max(max_y, py)
        span_x, span_y = max(max_x - min_x, 1), max(max_y - min_y, 1)
        scale = min((self.width() - 44) / (span_x + 2.5),
                    (self.height() - 44) / (span_y + 2.5)) * self.zoom
        scale = max(1.0, min(scale, 24.0))
        ox = self.width() / 2 - (min_x + max_x) * scale / 2
        oy = self.height() / 2 + (min_y + max_y) * scale / 2
        half_w, half_h = scale * 0.433, scale * 0.25
        painter.setPen(QPen(QColor("#111827"), max(0.5, scale * 0.025)))
        for _depth, px, py, color in sorted(projected, key=lambda v: v[0]):
            top = QPointF(ox + px * scale, oy - py * scale)
            left = QPointF(top.x() - half_w, top.y() + half_h)
            back = QPointF(top.x(), top.y() + half_h * 2)
            right = QPointF(top.x() + half_w, top.y() + half_h)
            down_left = QPointF(left.x(), left.y() + scale)
            down_back = QPointF(back.x(), back.y() + scale)
            down_right = QPointF(right.x(), right.y() + scale)
            painter.setBrush(color.lighter(125))
            painter.drawPolygon(QPolygonF([top, right, back, left]))
            painter.setBrush(color.darker(125))
            painter.drawPolygon(QPolygonF([left, back, down_back, down_left]))
            painter.setBrush(color.darker(150))
            painter.drawPolygon(QPolygonF([back, right, down_right, down_back]))
        painter.setPen(QColor("#9ca3af"))
        painter.drawText(12, 22, f"{len(self.blocks):,} preview blocks  ·  drag to rotate  ·  wheel to zoom")


class Worker(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(bool, str, object)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            pipeline = ModpackPipeline(self.cfg, self.log.emit, self.progress.emit)
            phase = self.cfg.get("phase")
            if phase == "choose_version":
                version, reason = pipeline.prepare_version()
                self.done.emit(True, f"Minecraft {version} selected. Create a matching Prism instance, then continue.", {
                    "phase": "version_ready", "version": version, "reason": reason
                })
                return
            if phase == "error_auto_fix":
                diagnosis = pipeline.diagnose_and_learn(self.cfg.get("error_text", ""))
                self.done.emit(True, "Error analysis saved. Review the diagnosis and confirm the lesson if it is accurate.", {
                    "phase": "diagnosis_ready", "diagnosis": diagnosis
                })
                return
            if phase == "catalog_sync":
                result = pipeline.sync_catalog(
                    self.cfg.get("catalog_query", ""),
                    self.cfg.get("catalog_source", "modrinth"),
                    self.cfg.get("catalog_version", "1.20.1"),
                    self.cfg.get("catalog_loader", "forge")
                )
                self.done.emit(True, f"Indexed {result['saved']} mod project(s) into the local database.", {
                    "phase": "catalog_synced", **result
                })
                return
            if phase == "retry_quests":
                result = pipeline.retry_quests_only()
                self.done.emit(bool(result.get("success")), result.get("message", "Quest retry finished."), {
                    "phase": "quests_retried", **result
                })
                return
            if phase == "structure_generate":
                from .structure_generator import generate_structure
                result = generate_structure(
                    pipeline.llm,
                    self.cfg.get("structure_description", ""),
                    self.cfg.get("structure_version", "1.16.5"),
                    self.cfg.get("structure_output", ""),
                    self.log.emit,
                    self.progress.emit,
                    self.cfg.get("structure_palette", {})
                )
                self.done.emit(True, "Structure generated successfully.", {
                    "phase": "structure_generated", **result
                })
                return
            result = pipeline.run()
            if isinstance(result, dict):
                self.done.emit(bool(result.get("success", True)), result.get(
                    "message", "Generation completed. Review the log and manifest."
                ), {"phase": "complete", **result})
            else:
                self.done.emit(True, "Generation completed. Review the log and manifest.", {"phase": "complete"})
        except Exception as exc:
            self.log.emit(f"ERROR · {type(exc).__name__}: {exc}")
            self.done.emit(False, str(exc), {"phase": self.cfg.get("phase", "complete")})


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modpack AI Studio")
        self.resize(1080, 850)
        self.elapsed = QElapsedTimer()
        self.phase = "choose_version"
        self.selected_version = None
        self.version_reason = ""
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.update_elapsed)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        header = QVBoxLayout()
        title = QLabel("MODPACK AI STUDIO")
        title.setObjectName("appTitle")
        subtitle = QLabel("Build, verify and install Minecraft modpacks with local AI.")
        subtitle.setObjectName("subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        progress_group = QGroupBox("Generation status")
        progress_layout = QVBoxLayout(progress_group)
        status_row = QHBoxLayout()
        self.stage_label = QLabel("Ready when you are.")
        self.stage_label.setObjectName("stageLabel")
        self.elapsed_label = QLabel("00:00 elapsed")
        self.elapsed_label.setObjectName("elapsedLabel")
        status_row.addWidget(self.stage_label, 1)
        status_row.addWidget(self.elapsed_label)
        progress_layout.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        progress_layout.addWidget(self.progress)
        layout.addWidget(progress_group)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        create_page = QWidget()
        create_layout = QVBoxLayout(create_page)
        create_layout.setContentsMargins(12, 14, 12, 12)
        create_layout.setSpacing(10)

        config_group = QGroupBox("AI and Minecraft")
        grid = QFormLayout(config_group)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.provider = QComboBox()
        self.provider.addItems(["Ollama (local, free)", "OpenAI", "Google Gemini"])
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem("qwen2.5:3b")
        self.model.setCurrentText("qwen2.5:3b")
        self.model.setMinimumWidth(220)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.ollama = QLineEdit("http://localhost:11434")
        self.ollama_start = QPushButton("Start Ollama")
        self.ollama_start.setObjectName("secondaryButton")
        self.ollama_start.clicked.connect(self.start_ollama)
        self.ollama_refresh = QPushButton("Refresh models")
        self.ollama_refresh.setObjectName("secondaryButton")
        self.ollama_refresh.clicked.connect(self.refresh_ollama_models)
        self.ollama_status = QLabel("Checking local Ollama…")
        self.ollama_status.setObjectName("subtitle")
        self._ollama_start_attempts = 0
        self.auto_version = QCheckBox("AI chooses the Minecraft version from my prompt")
        self.auto_version.setChecked(True)
        self.version = QLineEdit("1.20.1")
        self.version.setToolTip("The AI-selected Minecraft version appears here.")
        self.loader = QComboBox()
        self.loader.addItems(["forge", "fabric", "neoforge", "quilt"])

        self.instance = QLineEdit()
        self.instance.setEnabled(False)
        self.instance.setPlaceholderText("Create the matching Prism instance, then select its folder")
        browse = QPushButton("Browse…")
        browse.setObjectName("secondaryButton")
        browse.clicked.connect(self.browse)
        self.browse_button = browse
        browse.setEnabled(False)
        instance_row = QHBoxLayout()
        instance_row.addWidget(self.instance, 1)
        instance_row.addWidget(browse)

        grid.addRow("AI provider", self.provider)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.ollama_refresh)
        grid.addRow("Model", model_row)
        grid.addRow("API key", self.key)
        ollama_row = QHBoxLayout()
        ollama_row.addWidget(self.ollama, 1)
        ollama_row.addWidget(self.ollama_start)
        grid.addRow("Ollama server", ollama_row)
        grid.addRow("Ollama status", self.ollama_status)
        grid.addRow(self.auto_version)
        grid.addRow("Manual Minecraft version", self.version)
        grid.addRow("Modloader", self.loader)
        grid.addRow("Prism instance", instance_row)

        self.world_path = QLineEdit()
        self.world_path.setEnabled(False)
        self.world_path.setPlaceholderText(
            "Optional: select an existing world folder (the one containing level.dat)"
        )
        self.world_browse = QPushButton("Select world…")
        self.world_browse.setObjectName("secondaryButton")
        self.world_browse.setEnabled(False)
        self.world_browse.clicked.connect(self.browse_world)
        world_row = QHBoxLayout()
        world_row.addWidget(self.world_path, 1)
        world_row.addWidget(self.world_browse)
        grid.addRow("Install quests into world", world_row)
        create_layout.addWidget(config_group)

        prompt_group = QGroupBox("Describe your modpack")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText(
            "Describe the experience you want: progression, survival, technology, "
            "difficulty, exploration, preferred Minecraft version and required mods…"
        )
        self.prompt.setMinimumHeight(170)
        prompt_layout.addWidget(self.prompt)
        create_layout.addWidget(prompt_group, 1)

        options_row = QHBoxLayout()
        self.quests = QCheckBox("Generate a progression-sized custom quest campaign (no quest mod needed)")
        self.quests.setChecked(True)
        self.browser_research = QCheckBox("Use optional Playwright browser research (slower; requires browser setup)")
        self.browser_research.setChecked(False)
        self.backup = QCheckBox("Back up existing mods folder")
        self.backup.setChecked(True)
        options_row.addWidget(self.quests)
        options_row.addWidget(self.browser_research)
        options_row.addWidget(self.backup)
        options_row.addStretch(1)
        create_layout.addLayout(options_row)

        self.runbtn = QPushButton("1. Ask AI to choose Minecraft version")
        self.runbtn.setMinimumHeight(42)
        self.runbtn.clicked.connect(self.start)
        create_layout.addWidget(self.runbtn)

        # Keep the Create page usable on smaller displays and when maximized.
        create_scroll = QScrollArea()
        create_scroll.setWidgetResizable(True)
        create_scroll.setFrameShape(QScrollArea.NoFrame)
        create_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        create_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        create_scroll.setWidget(create_page)
        tabs.addTab(create_scroll, "Create")

        activity_page = QWidget()
        activity_layout = QVBoxLayout(activity_page)
        activity_layout.setContentsMargins(12, 14, 12, 12)
        activity_header = QHBoxLayout()
        activity_title = QLabel("Activity log")
        activity_title.setObjectName("sectionTitle")
        clear_button = QPushButton("Clear log")
        clear_button.setObjectName("secondaryButton")
        clear_button.clicked.connect(lambda: self.log.clear())
        activity_header.addWidget(activity_title)
        activity_header.addStretch(1)
        activity_header.addWidget(clear_button)
        activity_layout.addLayout(activity_header)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Generation events and diagnostic details will appear here.")
        self.log.setStyleSheet(
            "QTextEdit { background: #080e18; color: #b9d8c5; "
            "font-family: 'DejaVu Sans Mono'; font-size: 12px; }"
        )
        activity_layout.addWidget(self.log, 1)
        tabs.addTab(activity_page, "Activity")

        error_page = QWidget()
        error_layout = QVBoxLayout(error_page)
        error_layout.setContentsMargins(12, 14, 12, 12)
        error_layout.addWidget(QLabel(
            "Paste a Minecraft/Forge/Prism or app error log, or analyze the current Activity log. "
            "The model diagnoses and records a lesson. It does not silently edit code or delete files."
        ))
        self.error_input = QTextEdit()
        self.error_input.setPlaceholderText("Paste the complete relevant error log here…")
        self.error_input.setMinimumHeight(150)
        error_layout.addWidget(self.error_input)
        error_actions = QHBoxLayout()
        self.analyze_button = QPushButton("Error Auto Fix · Analyze")
        self.analyze_button.clicked.connect(self.analyze_error)
        self.analyze_log_button = QPushButton("Use Activity log")
        self.analyze_log_button.setObjectName("secondaryButton")
        self.analyze_log_button.clicked.connect(lambda: self.error_input.setPlainText(self.log.toPlainText()))
        self.confirm_lesson_button = QPushButton("Confirm latest lesson")
        self.confirm_lesson_button.setObjectName("secondaryButton")
        self.confirm_lesson_button.clicked.connect(self.confirm_error_lesson)
        error_actions.addWidget(self.analyze_button)
        error_actions.addWidget(self.analyze_log_button)
        error_actions.addWidget(self.confirm_lesson_button)
        error_layout.addLayout(error_actions)
        self.error_output = QTextEdit()
        self.error_output.setReadOnly(True)
        self.error_output.setPlaceholderText("The diagnosis and safe repair steps will appear here.")
        error_layout.addWidget(self.error_output, 1)
        self.retry_quests_button = QPushButton("Retry quest generation only · do not reinstall mods")
        self.retry_quests_button.setObjectName("secondaryButton")
        self.retry_quests_button.clicked.connect(self.retry_quests)
        error_layout.addWidget(self.retry_quests_button)
        tabs.addTab(error_page, "Error Auto Fix")

        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        library_layout.setContentsMargins(12, 14, 12, 12)
        library_layout.addWidget(QLabel(
            "Local SQLite library of mod metadata from Modrinth and CurseForge. "
            "It grows as you sync catalogs and generate modpacks. Descriptions and compatibility tags are cached locally."
        ))
        library_form = QFormLayout()
        self.library_query = QLineEdit()
        self.library_query.setPlaceholderText("Search name, description, category, or gameplay feature…")
        self.library_filter = QComboBox()
        self.library_filter.addItems(["All sources", "Modrinth", "CurseForge"])
        self.library_version = QLineEdit("1.16.5")
        self.library_loader = QComboBox()
        self.library_loader.addItems(["forge", "fabric", "neoforge", "quilt"])
        self.library_source = QComboBox()
        self.library_source.addItems(["Modrinth", "CurseForge"])
        self.library_cf_key = QLineEdit()
        self.library_cf_key.setEchoMode(QLineEdit.Password)
        self.library_cf_key.setPlaceholderText("Your personal CurseForge API key (stored in desktop keyring)")
        try:
            self.library_cf_key.setText(keyring.get_password(SERVICE, "curseforge-catalog") or "")
        except Exception:
            pass
        library_form.addRow("Search local database", self.library_query)
        library_form.addRow("Show source", self.library_filter)
        library_form.addRow("Online catalog to sync", self.library_source)
        library_form.addRow("Minecraft version", self.library_version)
        library_form.addRow("Loader", self.library_loader)
        library_form.addRow("CurseForge API key", self.library_cf_key)
        library_layout.addLayout(library_form)
        library_actions = QHBoxLayout()
        self.library_search_button = QPushButton("Search local library")
        self.library_search_button.clicked.connect(self.search_mod_library)
        self.library_sync_button = QPushButton("Sync from selected catalog")
        self.library_sync_button.clicked.connect(self.sync_mod_library)
        self.library_sync_button.setObjectName("secondaryButton")
        library_actions.addWidget(self.library_search_button)
        library_actions.addWidget(self.library_sync_button)
        library_layout.addLayout(library_actions)
        self.library_stats = QLabel("Local database: initializing…")
        self.library_stats.setObjectName("subtitle")
        library_layout.addWidget(self.library_stats)
        self.library_results = QTextEdit()
        self.library_results.setReadOnly(True)
        self.library_results.setPlaceholderText("Search the local library or sync compatible projects from an official catalog.")
        library_layout.addWidget(self.library_results, 1)
        tabs.addTab(library_page, "Mod Library")
        self.refresh_library_stats()

        structure_page = QWidget()
        structure_layout = QVBoxLayout(structure_page)
        structure_layout.setContentsMargins(12, 14, 12, 12)
        structure_layout.addWidget(QLabel(
            "Describe a custom Minecraft building. Qwen designs a compact blueprint; "
            "the procedural builder creates the blocks and exports a vanilla structure NBT. "
            "The first exporter targets Minecraft Java 1.16.5."
        ))
        structure_form = QFormLayout()
        self.structure_version = QComboBox()
        self.structure_version.addItem("Minecraft Java 1.16.5")
        self.structure_description = QTextEdit()
        self.structure_description.setMinimumHeight(180)
        self.structure_description.setPlaceholderText(
            "Example: An abandoned medieval watchtower, 3 floors, mossy stone, "
            "a library, a hidden treasure room, a balcony and a broken roof. "
            "Keep it compact and suitable for survival."
        )
        self.structure_output = QLineEdit(
            str(Path.home() / "Modpack-AI-Studio" / "generated_structures" / "custom_structure.nbt")
        )
        structure_browse = QPushButton("Save as…")
        structure_browse.setObjectName("secondaryButton")
        structure_browse.clicked.connect(self.browse_structure_output)
        structure_output_row = QHBoxLayout()
        structure_output_row.addWidget(self.structure_output, 1)
        structure_output_row.addWidget(structure_browse)
        self.structure_palette = QTextEdit()
        self.structure_palette.setMaximumHeight(78)
        self.structure_palette.setPlaceholderText(
            'Optional mod block palette JSON, e.g. {"create_brass":"create:brass_block","copper_casing":"create:copper_casing"}'
        )
        structure_form.addRow("Target version", self.structure_version)
        structure_form.addRow("Output file", structure_output_row)
        structure_form.addRow("Optional mod block palette", self.structure_palette)
        structure_layout.addLayout(structure_form)
        structure_layout.addWidget(QLabel(
            "Supports single builds, settlements, real underground dungeons and custom namespace:block IDs. "
            "Preview: drag to rotate, wheel to zoom. Export remains Minecraft Java 1.16.5 NBT. "
            "Mod block IDs are syntax-checked, not verified against installed mod registries."
        ))
        self.structure_generate_button = QPushButton("Generate structure / settlement with AI")
        self.structure_generate_button.setMinimumHeight(42)
        self.structure_generate_button.clicked.connect(self.generate_structure)
        structure_layout.addWidget(self.structure_generate_button)
        self.structure_preview = StructurePreview()
        structure_layout.addWidget(self.structure_preview, 2)
        self.structure_result = QTextEdit()
        self.structure_result.setReadOnly(True)
        self.structure_result.setPlaceholderText("Blueprint summary, block count and output path will appear here.")
        structure_layout.addWidget(self.structure_result, 1)
        tabs.addTab(structure_page, "Structure Designer")

        self.provider.currentTextChanged.connect(self.provider_changed)
        self.provider_changed(self.provider.currentText())
        self.model.currentTextChanged.connect(self.model_changed)
        QTimer.singleShot(250, self.refresh_ollama_models)
        self.auto_version.setEnabled(False)
        self.version.setReadOnly(True)
        self.version.setEnabled(False)
        self.version.setToolTip("The selected target version will appear here. Create a matching Prism instance before continuing.")
        self.statusBar().showMessage("Step 1 · Let the AI choose the Minecraft version")

    def provider_changed(self, provider):
        local = provider.startswith("Ollama")
        self.key.setEnabled(not local)
        self.ollama.setEnabled(local)
        self.ollama_start.setEnabled(local)
        self.ollama_refresh.setEnabled(local)
        self.model.setEnabled(True)
        if local:
            self.model.setCurrentText("qwen2.5:3b")
            self.ollama_status.setText("Local model server · Ollama")
        else:
            self.model.setCurrentText(
                "gpt-4.1-mini" if provider == "OpenAI" else "gemini-2.5-flash"
            )
            self.ollama_status.setText("Ollama controls are available with the local provider.")

    def ollama_base_url(self):
        return self.ollama.text().strip().rstrip("/")

    def check_ollama(self):
        try:
            response = requests.get(f"{self.ollama_base_url()}/api/tags", timeout=1.5)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            return None

    def refresh_ollama_models(self):
        if not self.provider.currentText().startswith("Ollama"):
            return
        data = self.check_ollama()
        if data is None:
            self.ollama_status.setText("Offline · click Start Ollama")
            return
        models = [
            item.get("name", "")
            for item in data.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]
        selected = self.model.currentText().strip()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(models)
        if selected and self.model.findText(selected) < 0:
            self.model.addItem(selected)
        if selected:
            self.model.setCurrentText(selected)
        elif models:
            self.model.setCurrentIndex(0)
        self.model.blockSignals(False)
        self.ollama_status.setText(
            f"Online · {len(models)} model(s) installed" if models
            else "Online · no models installed. Use 'ollama pull model-name' to add one."
        )

    def model_changed(self, _model):
        # The selected model is read from the combo when the generation starts.
        pass

    def start_ollama(self):
        if not self.provider.currentText().startswith("Ollama"):
            self.provider.setCurrentText("Ollama (local, free)")
        if self.check_ollama() is not None:
            self.ollama_status.setText("Online · Ollama is already running")
            self.refresh_ollama_models()
            return
        executable = shutil.which("ollama")
        if not executable:
            QMessageBox.warning(
                self, "Ollama not found",
                "The ollama command was not found. Install Ollama first, then click Start Ollama again."
            )
            self.ollama_status.setText("Not installed · install Ollama first")
            return
        try:
            subprocess.Popen(
                [executable, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Could not start Ollama", str(exc))
            return
        self._ollama_start_attempts = 0
        self.ollama_start.setEnabled(False)
        self.ollama_status.setText("Starting Ollama…")
        QTimer.singleShot(700, self.poll_ollama_startup)

    def poll_ollama_startup(self):
        data = self.check_ollama()
        if data is not None:
            self.ollama_start.setEnabled(self.provider.currentText().startswith("Ollama"))
            self.refresh_ollama_models()
            return
        self._ollama_start_attempts += 1
        if self._ollama_start_attempts >= 20:
            self.ollama_start.setEnabled(self.provider.currentText().startswith("Ollama"))
            self.ollama_status.setText("Could not connect · check the Ollama service and URL")
            QMessageBox.warning(
                self, "Ollama did not start",
                "Ollama did not respond at the configured URL. Check whether another service is using the port "
                "or whether the Ollama server is installed correctly."
            )
            return
        QTimer.singleShot(500, self.poll_ollama_startup)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Prism Launcher instance")
        if path:
            self.instance.setText(path)

    def browse_world(self):
        path = QFileDialog.getExistingDirectory(self, "Select Minecraft world folder")
        if path:
            if not (Path(path) / "level.dat").is_file():
                QMessageBox.warning(
                    self, "Not a Minecraft world",
                    "Select the world save folder containing level.dat, not the saves folder itself."
                )
                return
            self.world_path.setText(path)

    def browse_structure_output(self):
        current = self.structure_output.text().strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Minecraft structure", current or str(Path.home() / "custom_structure.nbt"),
            "Minecraft structure (*.nbt)"
        )
        if path:
            if not path.lower().endswith(".nbt"):
                path += ".nbt"
            self.structure_output.setText(path)

    def generate_structure(self):
        description = self.structure_description.toPlainText().strip()
        output = self.structure_output.text().strip()
        if not description:
            QMessageBox.warning(self, "Structure description required", "Describe the building you want to create.")
            return
        if not output:
            QMessageBox.warning(self, "Output path required", "Choose where to save the .nbt structure file.")
            return
        if Path(output).suffix.lower() != ".nbt":
            QMessageBox.warning(self, "Invalid output", "The output filename must end in .nbt.")
            return
        cfg = self.build_ai_config()
        if cfg is None:
            return
        cfg["phase"] = "structure_generate"
        cfg["structure_description"] = description
        cfg["structure_version"] = "1.16.5"
        cfg["structure_output"] = str(Path(output).expanduser())
        palette_text = self.structure_palette.toPlainText().strip()
        if palette_text:
            import json
            try:
                palette = json.loads(palette_text)
                if not isinstance(palette, dict):
                    raise ValueError("Palette must be a JSON object.")
                cfg["structure_palette"] = palette
            except (json.JSONDecodeError, ValueError) as exc:
                QMessageBox.warning(self, "Invalid block palette", str(exc))
                return
        else:
            cfg["structure_palette"] = {}
        self.launch_worker(cfg)

    def start(self):
        if self.phase == "choose_version":
            self.choose_version()
        else:
            self.continue_generation()

    def refresh_library_stats(self):
        try:
            stats = ModDatabase().stats()
            modrinth = stats.get("modrinth", {}).get("total", 0)
            curseforge = stats.get("curseforge", {}).get("total", 0)
            self.library_stats.setText(
                f"Local database: {modrinth} Modrinth project(s) · {curseforge} CurseForge project(s)"
            )
        except Exception as exc:
            self.library_stats.setText(f"Database unavailable: {exc}")

    def search_mod_library(self):
        query = self.library_query.text().strip()
        source = self.library_filter.currentText().lower()
        source = "all" if source == "all sources" else source
        try:
            records = ModDatabase().search(
                query, source=source, limit=100,
                game_version=self.library_version.text().strip(),
                loader=self.library_loader.currentText()
            )
        except Exception as exc:
            QMessageBox.warning(self, "Database error", str(exc))
            return
        if not records:
            self.library_results.setPlainText(
                "No local results yet. Use 'Sync from selected catalog' to import official catalog records."
            )
            return
        sections = []
        for item in records:
            sections.append(
                f"{item['name']} [{item['source'].upper()} · {item['project_id']}]\n"
                f"Summary: {item['summary']}\n"
                f"Description:\n{item['description'] or '(Full description not cached yet)'}\n"
                f"Authors: {', '.join(item['authors']) or 'Unknown'}\n"
                f"Categories: {', '.join(item['categories'])}\n"
                f"Minecraft: {', '.join(item['game_versions'])}\n"
                f"Loaders: {', '.join(item['loaders'])}\n"
                f"Downloads: {item['downloads']:,}\n"
                f"License: {item['license'] or 'Not listed'}\n"
                f"Website: {item['website'] or 'Not listed'}\n"
                f"Icon: {item['icon_url'] or 'Not listed'}\n"
                f"Last synced: {item['last_synced']}"
            )
        self.library_results.setPlainText("\n\n" + ("\n\n" + ("-" * 72) + "\n\n").join(sections))
        self.refresh_library_stats()

    def sync_mod_library(self):
        query = self.library_query.text().strip()
        if not query:
            QMessageBox.warning(self, "Search term required", "Enter a mod name, category, or feature to sync.")
            return
        source = self.library_source.currentText()
        api_key = self.library_cf_key.text().strip()
        if source == "CurseForge":
            if not api_key:
                try:
                    api_key = keyring.get_password(SERVICE, "curseforge-catalog") or ""
                except Exception:
                    api_key = ""
            if not api_key:
                QMessageBox.warning(
                    self, "CurseForge API key required",
                    "CurseForge's official API requires your own API key. It is stored in the desktop keyring, not in the database."
                )
                return
            try:
                keyring.set_password(SERVICE, "curseforge-catalog", api_key)
            except Exception as exc:
                QMessageBox.warning(self, "Keyring unavailable", str(exc))
                return
        cfg = {
            "provider": "Ollama", "model": "qwen2.5:3b", "api_key": "",
            "ollama_url": "http://localhost:11434",
            "catalog": source, "curseforge_key": api_key,
            "catalog_query": query, "catalog_source": source.lower(),
            "catalog_version": self.library_version.text().strip(),
            "catalog_loader": self.library_loader.currentText(),
            "phase": "catalog_sync"
        }
        self.launch_worker(cfg)

    def analyze_error(self):
        error_text = self.error_input.toPlainText().strip()
        if not error_text:
            QMessageBox.warning(self, "No error log", "Paste a log or click 'Use Activity log' first.")
            return
        cfg = self.build_ai_config()
        if cfg is None:
            return
        cfg["phase"] = "error_auto_fix"
        cfg["error_text"] = error_text
        self.launch_worker(cfg)

    def retry_quests(self):
        cfg = self.build_ai_config()
        if cfg is None:
            return
        instance = Path(self.instance.text()).expanduser()
        if not instance.is_dir():
            QMessageBox.warning(
                self, "Prism instance required",
                "Select the Prism instance where this app installed the mods. Quest retry will not reinstall or modify mods."
            )
            return
        cfg["instance"] = str(instance)
        cfg["world_path"] = self.world_path.text().strip()
        cfg["phase"] = "retry_quests"
        self.launch_worker(cfg)

    def confirm_error_lesson(self):
        from .error_memory import confirm_latest_lesson
        if confirm_latest_lesson():
            QMessageBox.information(
                self, "Lesson confirmed",
                "The latest unverified lesson is now eligible to be included in future AI error analyses and generation prompts."
            )
        else:
            QMessageBox.information(self, "No pending lesson", "There is no unverified lesson to confirm.")

    def build_ai_config(self):
        selected_provider = self.provider.currentText()
        provider = "Ollama" if selected_provider.startswith("Ollama") else selected_provider
        key = self.key.text().strip()
        if provider != "Ollama":
            if not key:
                key = keyring.get_password(SERVICE, provider) or ""
            if not key:
                QMessageBox.warning(self, "API key required", "Enter an API key or use local Ollama.")
                return None
        return {
            "provider": provider, "model": self.model.currentText().strip(),
            "api_key": key, "ollama_url": self.ollama.text().strip(),
            "version": self.version.text().strip(), "loader": self.loader.currentText(),
            "prompt": self.prompt.toPlainText(), "world_path": self.world_path.text().strip()
        }

    def build_config(self, include_instance=False):
        selected_provider = self.provider.currentText()
        provider = "Ollama" if selected_provider.startswith("Ollama") else selected_provider
        key = self.key.text().strip()

        if provider != "Ollama":
            if not key:
                key = keyring.get_password(SERVICE, provider) or ""
            if not key:
                QMessageBox.warning(self, "API key required", "Enter an API key or use local Ollama.")
                return
            try:
                keyring.set_password(SERVICE, provider, key)
            except Exception as exc:
                QMessageBox.warning(self, "Keyring unavailable", str(exc))
                return

        if not self.prompt.toPlainText().strip():
            QMessageBox.warning(self, "Missing prompt", "Describe the modpack first.")
            return None

        cfg = {
            "provider": provider,
            "model": self.model.currentText().strip(),
            "api_key": key,
            "ollama_url": self.ollama.text().strip(),
            "version": self.version.text().strip(),
            "auto_version": self.auto_version.isChecked(),
            "loader": self.loader.currentText(),
            "prompt": self.prompt.toPlainText(),
            "quests": self.quests.isChecked(),
            "browser_research": self.browser_research.isChecked(),
            "world_path": self.world_path.text().strip(),
            "backup": self.backup.isChecked(),
        }
        if include_instance:
            instance = Path(self.instance.text()).expanduser()
            if not instance.is_dir():
                QMessageBox.warning(self, "Invalid instance", "Choose an existing Prism instance folder.")
                return None
            cfg["instance"] = str(instance)
        return cfg

    def launch_worker(self, cfg):
        self.runbtn.setEnabled(False)
        for name in ("analyze_button", "analyze_log_button", "confirm_lesson_button", "retry_quests_button", "library_search_button", "library_sync_button", "structure_generate_button"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(False)
        self.log.clear() if cfg.get("phase") == "choose_version" else None
        self.elapsed.start()
        self.clock.start()
        self.elapsed_label.setText("00:00 elapsed")
        self.on_progress(0, 100, "Starting…")
        self.worker = Worker(cfg)
        self.worker.log.connect(self.log.append)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def choose_version(self):
        cfg = self.build_config()
        if cfg is None:
            return
        cfg["phase"] = "choose_version"
        self.launch_worker(cfg)

    def continue_generation(self):
        if not self.selected_version:
            QMessageBox.warning(self, "Version not selected", "Ask the AI to choose a version first.")
            return
        cfg = self.build_config(include_instance=True)
        if cfg is None:
            return
        cfg["version"] = self.selected_version
        cfg["auto_version"] = False
        cfg["version_preselected"] = True
        cfg["version_reason"] = self.version_reason
        cfg["version_selection"] = "ai"
        cfg["phase"] = "generate"
        self.launch_worker(cfg)

    def on_progress(self, value, maximum, message):
        self.stage_label.setText(message)
        if maximum <= 0:
            # Indeterminate means the local model is working but cannot expose
            # token-level progress for its current generation request.
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, maximum)
            self.progress.setValue(value)
            self.progress.setFormat("%p%")

    def update_elapsed(self):
        seconds = self.elapsed.elapsed() // 1000
        self.elapsed_label.setText(str(timedelta(seconds=seconds)).split(".")[0] + " elapsed")

    def finished(self, ok, message, payload):
        self.clock.stop()
        self.runbtn.setEnabled(True)
        for name in ("analyze_button", "analyze_log_button", "confirm_lesson_button", "retry_quests_button", "library_search_button", "library_sync_button", "structure_generate_button"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(True)
        payload = payload or {}
        if ok and payload.get("phase") == "version_ready":
            self.selected_version = payload["version"]
            self.version_reason = payload.get("reason", "")
            self.version.setText(self.selected_version)
            self.instance.setEnabled(True)
            self.browse_button.setEnabled(True)
            self.world_path.setEnabled(True)
            self.world_browse.setEnabled(True)
            # Freeze the inputs used for version selection so the target cannot drift
            # while the user creates the matching Prism instance.
            for widget in (
                self.provider, self.model, self.key, self.ollama,
                self.auto_version, self.loader, self.prompt, self.browser_research
            ):
                widget.setEnabled(False)
            self.runbtn.setText("2. Continue with this Prism instance")
            self.phase = "generate"
            self.on_progress(100, 100, f"Paused. Create a Minecraft {self.selected_version} Prism instance.")
            self.statusBar().showMessage("Paused · Create the matching Prism instance and select its folder")
            QMessageBox.information(
                self, "Version selected",
                f"The AI selected Minecraft {self.selected_version}.\n\n"
                f"Reason: {self.version_reason}\n\n"
                "Now open Prism Launcher, create a new instance with this exact Minecraft version "
                f"and the {self.loader.currentText()} loader, then return here and select that instance folder. "
                "The app will wait until you click Continue."
            )
            return

        if payload.get("phase") == "diagnosis_ready":
            diagnosis = payload.get("diagnosis", {})
            import json
            self.error_output.setPlainText(json.dumps(diagnosis, ensure_ascii=False, indent=2))
            self.statusBar().showMessage(message)
            QMessageBox.information(self, "Diagnosis complete", message)
            return
        if payload.get("phase") == "catalog_synced":
            self.refresh_library_stats()
            self.search_mod_library()
            self.statusBar().showMessage(message)
            QMessageBox.information(self, "Mod library updated", message)
            return
        if payload.get("phase") == "quests_retried":
            self.statusBar().showMessage(message)
            QMessageBox.information(self, "Quest retry", message)
            return
        if payload.get("phase") == "structure_generated":
            import json
            result = {
                "name": payload.get("name"),
                "minecraft": payload.get("minecraft"),
                "dimensions": payload.get("dimensions"),
                "block_count": payload.get("block_count"),
                "file": payload.get("file"),
                "blueprint": payload.get("blueprint"),
            }
            self.structure_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.structure_preview.set_blocks(payload.get("preview_blocks", []))
            self.statusBar().showMessage(message)
            QMessageBox.information(
                self, "Structure generated",
                f"{payload.get('name')}\n"
                f"Dimensions: {' × '.join(str(v) for v in payload.get('dimensions', []))}\n"
                f"Blocks: {payload.get('block_count', 0):,}\n\n"
                f"Saved to:\n{payload.get('file')}\n\n"
                "Import this .nbt with a compatible structure tool or a Minecraft Structure Block."
            )
            return

        if ok:
            partial = "quest generation failed" in message.lower()
            self.on_progress(
                100, 100,
                "Mods installed; quests need attention." if partial
                else "Finished. Review the installed mods and native quest datapack."
            )
            self.statusBar().showMessage(message)
        else:
            self.progress.setRange(0, 100)
            self.stage_label.setText("Stopped. Check the activity log for details.")
            self.statusBar().showMessage("Generation stopped")
        QMessageBox.information(self, "Completed" if ok else "Stopped", message)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
