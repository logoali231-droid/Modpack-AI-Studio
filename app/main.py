import sys
from pathlib import Path
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
 QLineEdit,QComboBox,QTextEdit,QPushButton,QLabel,QProgressBar,QFileDialog,QMessageBox,QGroupBox,QCheckBox,QTabWidget)
from PySide6.QtCore import QThread,Signal
import keyring
from .orchestrator import ModpackPipeline
SERVICE="modpack-ai-studio"
class Worker(QThread):
 log=Signal(str); done=Signal(bool,str)
 def __init__(self,cfg): super().__init__(); self.cfg=cfg
 def run(self):
  try: ModpackPipeline(self.cfg,self.log.emit).run(); self.done.emit(True,"Generation completed. Review the log and manifest.")
  except Exception as e: self.log.emit(f"ERROR · {type(e).__name__}: {e}"); self.done.emit(False,str(e))
class MainWindow(QMainWindow):
 def __init__(self):
  super().__init__(); self.setWindowTitle("Modpack AI Studio"); self.resize(1000,800)
  root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root)
  title=QLabel("MODPACK AI STUDIO"); title.setStyleSheet("font-size:26px;font-weight:900;color:#25445e")
  layout.addWidget(title); layout.addWidget(QLabel("Free, local-first modpack creation inspired by Modbot.gg"))
  tabs=QTabWidget(); layout.addWidget(tabs,1)
  page=QWidget(); form=QVBoxLayout(page); tabs.addTab(page,"Create")
  group=QGroupBox("AI & Minecraft configuration"); grid=QFormLayout(group)
  self.provider=QComboBox(); self.provider.addItems(["Ollama (local, free)","OpenAI","Google Gemini"])
  self.model=QLineEdit("qwen2.5:3b"); self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password)
  self.ollama=QLineEdit("http://localhost:11434"); self.version=QLineEdit("1.20.1")
  self.loader=QComboBox(); self.loader.addItems(["forge","fabric","neoforge","quilt"])
  self.instance=QLineEdit(); browse=QPushButton("Browse…"); browse.clicked.connect(self.browse)
  row=QHBoxLayout(); row.addWidget(self.instance); row.addWidget(browse)
  grid.addRow("AI provider",self.provider); grid.addRow("Model",self.model); grid.addRow("API key",self.key)
  grid.addRow("Ollama URL",self.ollama); grid.addRow("Minecraft version",self.version); grid.addRow("Modloader",self.loader); grid.addRow("Prism instance",row)
  form.addWidget(group)
  self.prompt=QTextEdit(); self.prompt.setPlaceholderText("Describe your modpack: theme, progression, tech, survival, performance limits…")
  self.prompt.setMinimumHeight(150); form.addWidget(QLabel("Describe the modpack")); form.addWidget(self.prompt)
  self.quests=QCheckBox("Generate a three-chapter FTB Quests campaign"); self.quests.setChecked(True)
  self.backup=QCheckBox("Back up existing mods folder"); self.backup.setChecked(True)
  form.addWidget(self.quests); form.addWidget(self.backup)
  self.runbtn=QPushButton("⚒ Generate Modpack & Quests"); self.runbtn.clicked.connect(self.start); form.addWidget(self.runbtn)
  activity=QWidget(); av=QVBoxLayout(activity); tabs.addTab(activity,"Activity")
  self.progress=QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); av.addWidget(self.progress)
  self.log=QTextEdit(); self.log.setReadOnly(True); self.log.setStyleSheet("background:#101820;color:#b8e6c1;font-family:monospace"); av.addWidget(self.log,1)
  self.provider.currentTextChanged.connect(self.provider_changed); self.provider_changed(self.provider.currentText())
  self.statusBar().showMessage("Ready · Ollama is the no-API-cost option")
 def provider_changed(self,p):
  local=p.startswith("Ollama"); self.key.setEnabled(not local); self.ollama.setEnabled(local)
  self.model.setText("qwen2.5:3b" if local else ("gpt-4.1-mini" if p=="OpenAI" else "gemini-2.5-flash"))
 def browse(self):
  p=QFileDialog.getExistingDirectory(self,"Select Prism Launcher instance")
  if p:self.instance.setText(p)
 def start(self):
  p=self.provider.currentText(); provider="Ollama" if p.startswith("Ollama") else p
  key=self.key.text().strip()
  if provider!="Ollama":
   if not key:key=keyring.get_password(SERVICE,provider) or ""
   if not key: QMessageBox.warning(self,"API key required","Enter an API key or use local Ollama."); return
   try:keyring.set_password(SERVICE,provider,key)
   except Exception as e: QMessageBox.warning(self,"Keyring unavailable",str(e)); return
  inst=Path(self.instance.text()).expanduser()
  if not inst.is_dir(): QMessageBox.warning(self,"Invalid instance","Choose an existing Prism instance folder."); return
  if not self.prompt.toPlainText().strip(): QMessageBox.warning(self,"Missing prompt","Describe the modpack first."); return
  self.runbtn.setEnabled(False); self.progress.show(); self.log.clear()
  cfg={"provider":provider,"model":self.model.text().strip(),"api_key":key,"ollama_url":self.ollama.text().strip(),
   "version":self.version.text().strip(),"loader":self.loader.currentText(),"instance":str(inst),
   "prompt":self.prompt.toPlainText(),"quests":self.quests.isChecked(),"backup":self.backup.isChecked()}
  self.worker=Worker(cfg); self.worker.log.connect(self.log.append); self.worker.done.connect(self.finished); self.worker.start()
 def finished(self,ok,msg):
  self.runbtn.setEnabled(True); self.progress.hide(); self.statusBar().showMessage(msg)
  QMessageBox.information(self,"Completed" if ok else "Stopped",msg)
def main():
 app=QApplication(sys.argv); w=MainWindow(); w.show(); sys.exit(app.exec())
if __name__=="__main__":main()
