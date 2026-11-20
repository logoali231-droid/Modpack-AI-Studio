"""GUI for the local modpack + native quest dataset pipeline."""
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QSpinBox,
    QLineEdit, QPushButton, QTextEdit, QMessageBox, QGroupBox, QProgressBar
)


class DatasetWorker(QThread):
    log = Signal(str)
    progress = Signal(int)
    done = Signal(bool, str)

    def __init__(self, root, model, count):
        super().__init__()
        self.root = Path(root)
        self.model = model
        self.count = count

    def run_command(self, label, args, env):
        self.log.emit("\n▶ " + label)
        process = subprocess.Popen(
            [sys.executable, *args],
            cwd=str(self.root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout:
            for line in process.stdout:
                self.log.emit(line.rstrip())
        code = process.wait()
        if code:
            raise RuntimeError(f"{label} terminou com código {code}.")

    def validate_jsonl(self, path):
        if not path.exists():
            raise RuntimeError(f"Arquivo não foi criado: {path}")
        total = 0
        with path.open("r", encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                messages = row.get("messages")
                if not isinstance(messages, list):
                    raise ValueError(f"{path.name}:{line_no}: campo messages ausente.")
                roles = [m.get("role") for m in messages if isinstance(m, dict)]
                if "user" not in roles or "assistant" not in roles:
                    raise ValueError(f"{path.name}:{line_no}: conversa incompleta.")
                if roles[-1] != "assistant":
                    raise ValueError(f"{path.name}:{line_no}: assistant deve ser a última mensagem.")
                total += 1
        if total == 0:
            raise RuntimeError(f"Nenhum exemplo válido em {path.name}.")
        self.log.emit(f"✓ {path.name}: {total} exemplos JSONL válidos.")
        return total

    def run(self):
        try:
            env = os.environ.copy()
            env["MODPACK_AI_MODEL"] = self.model
            env["PYTHONUTF8"] = "1"
            steps = [
                ("Exportar catálogo SQLite para JSONL",
                 ["training/scripts/export_mods.py"]),
                ("Gerar briefs de design",
                 ["training/scripts/generate_specs.py", "--count", str(self.count)]),
                ("Gerar dataset de design de modpacks",
                 ["training/scripts/build_modpack_dataset.py"]),
                ("Gerar dataset de quests nativas",
                 ["training/scripts/build_native_quest_dataset.py"]),
            ]
            for index, (label, args) in enumerate(steps, 1):
                self.progress.emit(index - 1)
                self.run_command(label, args, env)

            self.progress.emit(4)
            design = self.root / "training/datasets/modpack_design.jsonl"
            quests = self.root / "training/datasets/quest_generation.jsonl"
            mods = self.root / "training/data/raw/mod_knowledge.jsonl"
            self.validate_jsonl(design)
            self.validate_jsonl(quests)
            if not mods.exists() or mods.stat().st_size == 0:
                raise RuntimeError("O catálogo JSONL está vazio.")
            self.progress.emit(5)
            self.done.emit(True, "Os datasets de modpacks e quests foram gerados e validados.")
        except Exception as exc:
            self.log.emit(f"✗ ERRO: {type(exc).__name__}: {exc}")
            self.done.emit(False, str(exc))


class DatasetPanel(QWidget):
    """A single GUI entry point for catalog export and both SFT datasets."""

    def __init__(self, project_root, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        intro = QLabel(
            "Prepare os dados de especialização do Modpack AI Studio. "
            "Um clique exporta o catálogo local, cria briefs e gera os datasets "
            "de design de modpacks e de quests nativas do próprio aplicativo."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        settings = QGroupBox("Configuração")
        form = QFormLayout(settings)
        self.model = QLineEdit("qwen2.5:3b")
        self.model.setPlaceholderText("Nome exato do modelo instalado no Ollama")
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(100)
        self.count.setToolTip("Quantidade de briefs de design a gerar.")
        form.addRow("Modelo Ollama", self.model)
        form.addRow("Quantidade de briefs", self.count)
        layout.addWidget(settings)

        actions = QHBoxLayout()
        self.run_button = QPushButton("Gerar datasets de modpacks + quests")
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self.start_pipeline)
        self.open_folder_button = QPushButton("Abrir pasta training")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.clicked.connect(self.open_folder)
        actions.addWidget(self.run_button, 2)
        actions.addWidget(self.open_folder_button, 1)
        layout.addLayout(actions)

        self.status = QLabel("Pronto. Os arquivos existentes serão complementados, não apagados.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 5)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Etapas, avisos e validação dos datasets aparecerão aqui.")
        layout.addWidget(self.output, 1)

        note = QLabel(
            "Importante: a geração dos datasets usa o Ollama local. "
            "O ajuste QLoRA do modelo continua sendo uma etapa separada, normalmente "
            "executada em uma GPU compatível (por exemplo, Colab)."
        )
        note.setWordWrap(True)
        note.setObjectName("subtitle")
        layout.addWidget(note)

    def start_pipeline(self):
        if self.worker and self.worker.isRunning():
            return
        model = self.model.text().strip()
        if not model:
            QMessageBox.warning(self, "Modelo necessário", "Informe o nome do modelo Ollama.")
            return
        self.output.clear()
        self.status.setText("Pipeline em execução. Você pode acompanhar cada etapa abaixo.")
        self.progress.setValue(0)
        self.run_button.setEnabled(False)
        self.worker = DatasetWorker(self.project_root, model, self.count.value())
        self.worker.log.connect(self.output.append)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self.pipeline_finished)
        self.worker.start()

    def pipeline_finished(self, success, message):
        self.run_button.setEnabled(True)
        self.status.setText(message)
        if success:
            QMessageBox.information(self, "Datasets prontos", message)
        else:
            QMessageBox.warning(self, "Pipeline interrompido", message)

    def open_folder(self):
        import subprocess
        folder = self.project_root / "training"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            QMessageBox.warning(self, "Não foi possível abrir a pasta", str(exc))
