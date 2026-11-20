"""Run the experimental dataset pipeline from the desktop GUI."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TASKS = {
    "export_catalog": ("training/scripts/export_mods.py", []),
    "generate_specs": ("training/scripts/generate_specs.py", []),
    "build_modpack": ("training/scripts/build_modpack_dataset.py", []),
    "build_quests": ("training/scripts/build_quest_dataset.py", []),
    "export_errors": ("training/scripts/export_error_lessons.py", []),
    "validate": ("training/scripts/validate_datasets.py", []),
}


def run_training_task(task, log, model="qwen2.5:3b", ollama_url="http://localhost:11434", count=100, fresh=False):
    if task not in TASKS:
        raise ValueError(f"Unknown training task: {task}")
    script, args = TASKS[task]
    command = [sys.executable, str(ROOT / script), *args]
    if task == "generate_specs":
        command += ["--count", str(max(1, min(int(count), 1000)))]
    if fresh and task in ("build_modpack", "build_quests"):
        command.append("--fresh")

    env = os.environ.copy()
    env["MODPACK_AI_MODEL"] = str(model or "qwen2.5:3b")
    env["MODPACK_AI_OLLAMA_URL"] = str(ollama_url or "http://localhost:11434").rstrip("/")
    log("Running: " + " ".join(command))
    process = subprocess.Popen(
        command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", bufsize=1
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            log(line)
    code = process.wait()
    if code:
        raise RuntimeError(f"Training task '{task}' exited with code {code}.")
    return {"task": task, "success": True, "command": command}


def training_counts():
    datasets = ROOT / "training" / "datasets"
    result = {}
    for name in ("modpack_design.jsonl", "quest_generation.jsonl", "error_diagnosis.jsonl"):
        path = datasets / name
        result[name] = sum(1 for line in path.open(encoding="utf-8") if line.strip()) if path.is_file() else 0
    return result
