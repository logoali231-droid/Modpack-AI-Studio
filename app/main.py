import sys
from pathlib import Path
from datetime import timedelta
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QTextEdit, QPushButton, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QTabWidget, QScrollArea
)
from PySide6.QtCore import QThread, Signal, QTimer, QElapsedTimer, Qt
import keyring
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
            if self.cfg.get("phase") == "choose_version":
                version, reason = pipeline.prepare_version()
                self.done.emit(True, f"Minecraft {version} selected. Create a matching Prism instance, then continue.", {
                    "phase": "version_ready", "version": version, "reason": reason
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
        self.model = QLineEdit("qwen2.5:3b")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.ollama = QLineEdit("http://localhost:11434")
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
        grid.addRow("Model", self.model)
        grid.addRow("API key", self.key)
        grid.addRow("Ollama URL", self.ollama)
        grid.addRow(self.auto_version)
        grid.addRow("Manual Minecraft version", self.version)
        grid.addRow("Modloader", self.loader)
        grid.addRow("Prism instance", instance_row)
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
        self.quests = QCheckBox("Generate a three-chapter FTB Quests campaign")
        self.quests.setChecked(True)
        self.backup = QCheckBox("Back up existing mods folder")
        self.backup.setChecked(True)
        options_row.addWidget(self.quests)
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

        self.provider.currentTextChanged.connect(self.provider_changed)
        self.provider_changed(self.provider.currentText())
        self.auto_version.setEnabled(False)
        self.version.setReadOnly(True)
        self.version.setEnabled(False)
        self.version.setToolTip("The selected target version will appear here. Create a matching Prism instance before continuing.")
        self.statusBar().showMessage("Step 1 · Let the AI choose the Minecraft version")

    def provider_changed(self, provider):
        local = provider.startswith("Ollama")
        self.key.setEnabled(not local)
        self.ollama.setEnabled(local)
        self.model.setText(
            "qwen2.5:3b" if local else
            ("gpt-4.1-mini" if provider == "OpenAI" else "gemini-2.5-flash")
        )

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Prism Launcher instance")
        if path:
            self.instance.setText(path)

    def start(self):
        if self.phase == "choose_version":
            self.choose_version()
        else:
            self.continue_generation()

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
            "model": self.model.text().strip(),
            "api_key": key,
            "ollama_url": self.ollama.text().strip(),
            "version": self.version.text().strip(),
            "auto_version": self.auto_version.isChecked(),
            "loader": self.loader.currentText(),
            "prompt": self.prompt.toPlainText(),
            "quests": self.quests.isChecked(),
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
        payload = payload or {}
        if ok and payload.get("phase") == "version_ready":
            self.selected_version = payload["version"]
            self.version_reason = payload.get("reason", "")
            self.version.setText(self.selected_version)
            self.instance.setEnabled(True)
            self.browse_button.setEnabled(True)
            # Freeze the inputs used for version selection so the target cannot drift
            # while the user creates the matching Prism instance.
            for widget in (
                self.provider, self.model, self.key, self.ollama,
                self.auto_version, self.loader, self.prompt
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

        if ok:
            partial = "quest generation failed" in message.lower()
            self.on_progress(
                100, 100,
                "Mods installed; quests need attention." if partial
                else "Finished. Review the installed mods and quest files."
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
