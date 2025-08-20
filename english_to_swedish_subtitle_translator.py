import json
import os
import re
import time
import requests
from pathlib import Path
from threading import Lock
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QSettings, QStandardPaths
from PyQt6.QtGui import QAction, QIcon, QTextCursor, QPalette, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QGroupBox, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QLineEdit, QMenu, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QInputDialog, QStyleFactory
)

# ======================
# CONSTANTS & SETTINGS
# ======================
DEFAULT_BASE_URL = "http://localhost:11434/api/chat"
DEFAULT_TEMPERATURE = 0.2
RETRY_COUNT = 2
RETRY_DELAY = 5  # seconds
PROFILES_FILE = "profiles.json"
LANGUAGES = [
    ("German", "de"), ("French", "fr"), ("Spanish", "es"), ("Italian", "it"),
    ("Portuguese", "pt"), ("Russian", "ru"), ("Japanese", "ja"), ("Korean", "ko"),
    ("Chinese (Simplified)", "zh-CN"), ("Chinese (Traditional)", "zh-TW"), ("Arabic", "ar"),
    ("Hindi", "hi"), ("Turkish", "tr"), ("Dutch", "nl"), ("Polish", "pl"),
    ("Swedish", "sv"), ("Norwegian", "no"), ("Danish", "da"), ("Finnish", "fi"),
    ("Greek", "el"), ("Czech", "cs"), ("Hungarian", "hu"), ("Thai", "th"),
    ("Vietnamese", "vi"), ("Indonesian", "id"), ("Romanian", "ro"), ("Ukrainian", "uk")
]

STYLES = ["Natural (recommended)", "Formal", "Simple clear"]

THEMES = {
    "Light": {
        "window_bg": "#F0F0F0",
        "text_color": "#000000",
        "base_bg": "#FFFFFF",
        "button_bg": "#E0E0E0",
        "button_hover": "#D0D0D0",
        "progress_bg": "#E0E0E0",
        "progress_chunk": "#4CAF50",
        "log_bg": "#FFFFFF",
        "log_text": "#000000",
        "border": "#CCCCCC"
    },
    "Dark": {
        "window_bg": "#2D2D2D",
        "text_color": "#E0E0E0",
        "base_bg": "#3C3C3C",
        "button_bg": "#505050",
        "button_hover": "#606060",
        "progress_bg": "#404040",
        "progress_chunk": "#4CAF50",
        "log_bg": "#252525",
        "log_text": "#E0E0E0",
        "border": "#555555"
    },
    "Solarized Light": {
        "window_bg": "#FDF6E3",
        "text_color": "#586E75",
        "base_bg": "#EEE8D5",
        "button_bg": "#93A1A1",
        "button_hover": "#839496",
        "progress_bg": "#EEE8D5",
        "progress_chunk": "#859900",
        "log_bg": "#FDF6E3",
        "log_text": "#586E75",
        "border": "#93A1A1"
    },
    "Nord": {
        "window_bg": "#2E3440",
        "text_color": "#D8DEE9",
        "base_bg": "#3B4252",
        "button_bg": "#4C566A",
        "button_hover": "#5E81AC",
        "progress_bg": "#4C566A",
        "progress_chunk": "#A3BE8C",
        "log_bg": "#2E3440",
        "log_text": "#D8DEE9",
        "border": "#4C566A"
    },
    "Dracula": {
        "window_bg": "#282A36",
        "text_color": "#F8F8F2",
        "base_bg": "#44475A",
        "button_bg": "#6272A4",
        "button_hover": "#50FA7B",
        "progress_bg": "#44475A",
        "progress_chunk": "#FF79C6",
        "log_bg": "#282A36",
        "log_text": "#F8F8F2",
        "border": "#6272A4"
    }
}

# ======================
# WORKER THREAD
# ======================
class TranslationWorker(QThread):
    progress = pyqtSignal(int, int)  # current, total
    log_message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, files, target_lang, style, model, advanced_prompt, base_url, parent=None):
        super().__init__(parent)
        self.files = files
        self.target_lang = target_lang
        self.style = style
        self.model = model
        self.advanced_prompt = advanced_prompt
        self.base_url = base_url
        self._is_cancelled = False
        self.lock = Lock()

    def cancel(self):
        with self.lock:
            self._is_cancelled = True

    def is_cancelled(self):
        with self.lock:
            return self._is_cancelled

    def run(self):
        try:
            total_files = len(self.files)
            for idx, file_path in enumerate(self.files):
                if self.is_cancelled():
                    self.log_message.emit("Translation cancelled by user")
                    break
                
                self.log_message.emit(f"Processing file: {file_path}")
                self.progress.emit(idx, total_files)
                
                try:
                    self.process_file(file_path)
                except Exception as e:
                    self.log_message.emit(f"Error processing {file_path}: {str(e)}")
                
                if self.is_cancelled():
                    break
            
            self.progress.emit(total_files, total_files)
            if not self.is_cancelled():
                self.log_message.emit("Translation completed successfully!")
        except Exception as e:
            self.error.emit(f"Critical error: {str(e)}")
        finally:
            self.finished.emit()

    def process_file(self, file_path):
        # Skip if target file already exists
        target_path = self.get_target_path(file_path)
        if target_path.exists():
            self.log_message.emit(f"Skipping {file_path} - target already exists")
            return
        
        # Skip if file already has target language code in filename
        if f".{self.target_lang}." in file_path.lower():
            self.log_message.emit(f"Skipping {file_path} - already has target language code")
            return
        
        # Read and parse SRT file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        blocks = self.parse_srt(content)
        if not blocks:
            self.log_message.emit(f"No valid blocks found in {file_path}")
            return
        
        translated_blocks = []
        for block_idx, block in enumerate(blocks):
            if self.is_cancelled():
                return
                
            index, timecode, text = block
            self.log_message.emit(f"Translating block {block_idx+1}/{len(blocks)}")
            
            # Protect timecodes and HTML tags
            protected_text, replacements = self.protect_content(text)
            
            # Generate system prompt
            system_prompt = self.generate_system_prompt(protected_text)
            
            # Send to Ollama
            translated_text = self.translate_text(system_prompt, protected_text)
            if not translated_text:
                self.log_message.emit("Skipping block due to translation failure")
                translated_blocks.append((index, timecode, text))
                continue
            
            # Restore protected content
            restored_text = self.restore_content(translated_text, replacements)
            translated_blocks.append((index, timecode, restored_text))
        
        # Save translated SRT
        self.save_srt(target_path, translated_blocks)
        self.log_message.emit(f"Saved translated file: {target_path}")

    def get_target_path(self, file_path):
        path = Path(file_path)
        stem = path.stem
        
        # Remove any existing language codes from filename (e.g. .eng)
        stem = re.sub(r'\.[a-z]{2,3}(-[a-zA-Z]{2,3})?$', '', stem, flags=re.IGNORECASE)
        
        # Create new filename with target language code
        return path.parent / f"{stem}.{self.target_lang}{path.suffix}"

    def parse_srt(self, content):
        blocks = []
        pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|$)'
        matches = re.findall(pattern, content)
        
        for match in matches:
            index = match[0]
            timecode = match[1]
            text = match[2].strip()
            blocks.append((index, timecode, text))
        
        return blocks

    def protect_content(self, text):
        # Protect timecodes
        timecode_pattern = r'\d{2}:\d{2}:\d{2},\d{3}'
        replacements = {}
        protected_text = text
        
        # Replace timecodes
        timecodes = re.findall(timecode_pattern, text)
        for idx, tc in enumerate(timecodes):
            placeholder = f"<TIME_{idx}>"
            protected_text = protected_text.replace(tc, placeholder)
            replacements[placeholder] = tc
        
        # Protect HTML tags
        tag_pattern = r'<([^>]+)>'
        tags = re.findall(tag_pattern, text)
        for idx, tag in enumerate(tags):
            full_tag = f"<{tag}>"
            if full_tag.startswith('</'):
                placeholder = f"<ETAG_{idx}>"
            else:
                placeholder = f"<BTAG_{idx}>"
            protected_text = protected_text.replace(full_tag, placeholder)
            replacements[placeholder] = full_tag
        
        return protected_text, replacements

    def generate_system_prompt(self, protected_text):
        style_map = {
            "Natural (recommended)": "natural",
            "Formal": "formal",
            "Simple clear": "simple and clear"
        }
        style_desc = style_map.get(self.style, "natural")
        
        prompt = (
            f"Translate the following text from English into {self.target_lang}.\n"
            f"Use {style_desc} style. Important:\n"
            "Only translate the USER text.\n"
            "Keep placeholders like <BTAG_0>, <ETAG_0>, <TIME_0> unchanged.\n"
            "Never translate content inside placeholders.\n"
            "Do NOT add explanations or commentary.\n"
            "Answer with the translated text only."
        )
        
        if self.advanced_prompt.strip():
            prompt = self.advanced_prompt
        
        return prompt

    def translate_text(self, system_prompt, text):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "stream": False,
            "options": {"temperature": DEFAULT_TEMPERATURE}
        }
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                response = requests.post(self.base_url, json=payload, timeout=30)
                if response.status_code == 200:
                    return response.json()['message']['content']
                else:
                    self.log_message.emit(
                        f"API error (attempt {attempt+1}/{RETRY_COUNT+1}): "
                        f"{response.status_code} - {response.text}"
                    )
            except Exception as e:
                self.log_message.emit(
                    f"Network error (attempt {attempt+1}/{RETRY_COUNT+1}): {str(e)}"
                )
            
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
        
        return None

    def restore_content(self, text, replacements):
        restored_text = text
        for placeholder, original in replacements.items():
            restored_text = restored_text.replace(placeholder, original)
        return restored_text

    def save_srt(self, path, blocks):
        with open(path, 'w', encoding='utf-8') as f:
            for index, timecode, text in blocks:
                f.write(f"{index}\n{timecode}\n{text}\n\n")

# ======================
# DIALOGS
# ======================
class OllamaSettingsDialog(QDialog):
    def __init__(self, current_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ollama Settings")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        self.url_edit = QLineEdit(current_url)
        form_layout.addRow("API Base URL:", self.url_edit)
        
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                  QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def get_url(self):
        return self.url_edit.text().strip()

# ======================
# MAIN WINDOW
# ======================
class SRTTranslatorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SRT Translator (Ollama)")
        self.setMinimumSize(750, 700)
        
        # Initialize settings
        self.settings = QSettings("SRTTranslator", "OllamaTranslator")
        self.profiles = {}
        self.current_profile = "Default"
        self.base_url = DEFAULT_BASE_URL
        self.current_theme = "Light"
        self.selected_files = []
        
        # Setup UI first
        self.init_ui()
        
        # Then load settings
        self.load_settings()
        
        # Apply theme after UI is created
        self.apply_theme(self.current_theme)
        
        # Load models
        self.refresh_models()
        
        # Create worker thread
        self.worker_thread = None
    
    def init_ui(self):
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Model selection group
        model_group = QGroupBox("Model Selection")
        model_layout = QHBoxLayout()
        
        model_layout.addWidget(QLabel("Ollama Model:"))
        self.model_combo = QComboBox()
        model_layout.addWidget(self.model_combo, 3)
        
        self.refresh_btn = QPushButton("Refresh models")
        self.refresh_btn.clicked.connect(self.refresh_models)
        model_layout.addWidget(self.refresh_btn)
        
        self.model_status = QLabel("No models loaded")
        model_layout.addWidget(self.model_status)
        
        model_group.setLayout(model_layout)
        main_layout.addWidget(model_group)
        
        # Language/style group
        lang_group = QGroupBox("Translation Settings")
        lang_layout = QVBoxLayout()
        
        # Language selection
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Target Language:"))
        self.lang_combo = QComboBox()
        for name, code in LANGUAGES:
            self.lang_combo.addItem(name, code)
        lang_row.addWidget(self.lang_combo, 1)
        
        lang_row.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(STYLES)
        lang_row.addWidget(self.style_combo, 1)
        
        lang_layout.addLayout(lang_row)
        
        # Advanced prompt
        lang_layout.addWidget(QLabel("Advanced Prompt:"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Customize the system prompt (optional). Use {target_lang} and {style} as placeholders."
        )
        self.prompt_edit.setMinimumHeight(100)
        lang_layout.addWidget(self.prompt_edit)
        
        lang_group.setLayout(lang_layout)
        main_layout.addWidget(lang_group)
        
        # File selection group
        file_group = QGroupBox("File Selection")
        file_layout = QVBoxLayout()
        
        self.file_label = QLabel("No file or folder selected")
        file_layout.addWidget(self.file_label)
        
        file_btn_layout = QHBoxLayout()
        self.file_btn = QPushButton("Choose file (.srt)")
        self.file_btn.clicked.connect(self.select_file)
        file_btn_layout.addWidget(self.file_btn)
        
        self.folder_btn = QPushButton("Choose folder")
        self.folder_btn.clicked.connect(self.select_folder)
        file_btn_layout.addWidget(self.folder_btn)
        
        file_layout.addLayout(file_btn_layout)
        file_group.setLayout(file_layout)
        main_layout.addWidget(file_group)
        
        # Actions group
        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start translation")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        self.start_btn.clicked.connect(self.start_translation)
        action_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("Cancel translation")
        self.cancel_btn.setStyleSheet("background-color: #F44336; color: white;")
        self.cancel_btn.clicked.connect(self.cancel_translation)
        self.cancel_btn.setEnabled(False)
        action_layout.addWidget(self.cancel_btn)
        
        action_group.setLayout(action_layout)
        main_layout.addWidget(action_group)
        
        # Progress group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFontFamily("Courier New")
        self.log_view.setMinimumHeight(150)
        progress_layout.addWidget(self.log_view)
        
        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)
        
        # Tools group
        tools_group = QGroupBox("Tools")
        tools_layout = QHBoxLayout()
        
        self.clear_btn = QPushButton("Clear log")
        self.clear_btn.clicked.connect(self.clear_log)
        tools_layout.addWidget(self.clear_btn)
        
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self.open_output_folder)
        tools_layout.addWidget(self.open_btn)
        
        tools_layout.addStretch(1)
        tools_group.setLayout(tools_layout)
        main_layout.addWidget(tools_group)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def create_menu_bar(self):
        menu_bar = self.menuBar()
        
        # Settings menu
        settings_menu = menu_bar.addMenu("Settings")
        
        # Profiles submenu
        self.profiles_menu = QMenu("Profiles", self)
        self.update_profiles_menu()
        
        save_profile_action = QAction("Save profile", self)
        save_profile_action.triggered.connect(self.save_profile)
        
        save_as_action = QAction("Save as new profile", self)
        save_as_action.triggered.connect(self.save_as_new_profile)
        
        rename_action = QAction("Rename profile", self)
        rename_action.triggered.connect(self.rename_profile)
        
        delete_action = QAction("Delete profile", self)
        delete_action.triggered.connect(self.delete_profile)
        
        ollama_action = QAction("Ollama settings...", self)
        ollama_action.triggered.connect(self.open_ollama_settings)
        
        # Theme submenu
        theme_menu = QMenu("Theme", self)
        self.theme_actions = {}
        for theme_name in THEMES:
            action = QAction(theme_name, self, checkable=True)
            action.triggered.connect(lambda _, t=theme_name: self.apply_theme(t))
            theme_menu.addAction(action)
            self.theme_actions[theme_name] = action
        
        settings_menu.addMenu(self.profiles_menu)
        settings_menu.addAction(save_profile_action)
        settings_menu.addAction(save_as_action)
        settings_menu.addAction(rename_action)
        settings_menu.addAction(delete_action)
        settings_menu.addAction(ollama_action)
        settings_menu.addMenu(theme_menu)
    
    def update_profiles_menu(self):
        self.profiles_menu.clear()
        for profile_name in self.profiles:
            action = QAction(profile_name, self, checkable=True)
            action.triggered.connect(lambda _, p=profile_name: self.load_profile(p))
            self.profiles_menu.addAction(action)
            if profile_name == self.current_profile:
                action.setChecked(True)
    
    def load_settings(self):
        # Load base URL
        self.base_url = self.settings.value("base_url", DEFAULT_BASE_URL)
        
        # Load theme
        self.current_theme = self.settings.value("theme", "Light")
        
        # Load profiles
        profiles_path = self.get_profiles_path()
        if profiles_path.exists():
            try:
                with open(profiles_path, 'r') as f:
                    self.profiles = json.load(f)
            except:
                self.profiles = {}
        
        # Load current profile
        self.current_profile = self.settings.value("current_profile", "Default")
        if self.current_profile not in self.profiles:
            self.create_default_profile()
        self.load_profile(self.current_profile)
    
    def save_settings(self):
        self.settings.setValue("base_url", self.base_url)
        self.settings.setValue("theme", self.current_theme)
        self.settings.setValue("current_profile", self.current_profile)
        
        # Save profiles
        profiles_path = self.get_profiles_path()
        with open(profiles_path, 'w') as f:
            json.dump(self.profiles, f, indent=2)
    
    def get_profiles_path(self):
        config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / PROFILES_FILE
    
    def create_default_profile(self):
        self.profiles["Default"] = {
            "model": "",
            "target_language": "de",
            "style": "Natural (recommended)",
            "advanced_prompt": ""
        }
    
    def load_profile(self, profile_name):
        if profile_name not in self.profiles:
            return
        
        profile = self.profiles[profile_name]
        self.current_profile = profile_name
        
        # Update UI from profile
        if "model" in profile:
            self.model_combo.setCurrentText(profile["model"])
        
        if "target_language" in profile:
            lang_code = profile["target_language"]
            lang_index = self.lang_combo.findData(lang_code)
            if lang_index >= 0:
                self.lang_combo.setCurrentIndex(lang_index)
        
        if "style" in profile:
            style = profile["style"]
            style_index = self.style_combo.findText(style)
            if style_index >= 0:
                self.style_combo.setCurrentIndex(style_index)
        
        if "advanced_prompt" in profile:
            self.prompt_edit.setPlainText(profile["advanced_prompt"])
        
        # Update menu checks
        self.update_profiles_menu()
        self.statusBar().showMessage(f"Loaded profile: {profile_name}")
    
    def save_profile(self):
        if self.current_profile not in self.profiles:
            return
        
        self.save_current_to_profile(self.current_profile)
        self.save_settings()
        self.statusBar().showMessage(f"Profile saved: {self.current_profile}")
    
    def save_current_to_profile(self, profile_name):
        self.profiles[profile_name] = {
            "model": self.model_combo.currentText(),
            "target_language": self.lang_combo.currentData(),
            "style": self.style_combo.currentText(),
            "advanced_prompt": self.prompt_edit.toPlainText()
        }
    
    def save_as_new_profile(self):
        name, ok = QInputDialog.getText(
            self, "New Profile", "Enter profile name:"
        )
        if ok and name:
            if name in self.profiles:
                QMessageBox.warning(self, "Duplicate Name", 
                                    "A profile with this name already exists.")
                return
            
            self.save_current_to_profile(name)
            self.current_profile = name
            self.save_settings()
            self.update_profiles_menu()
            self.statusBar().showMessage(f"Created new profile: {name}")
    
    def rename_profile(self):
        if self.current_profile == "Default":
            QMessageBox.warning(self, "Cannot Rename", 
                                "The default profile cannot be renamed.")
            return
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "Enter new profile name:",
            text=self.current_profile
        )
        if ok and new_name and new_name != self.current_profile:
            if new_name in self.profiles:
                QMessageBox.warning(self, "Duplicate Name", 
                                    "A profile with this name already exists.")
                return
            
            self.profiles[new_name] = self.profiles.pop(self.current_profile)
            self.current_profile = new_name
            self.save_settings()
            self.update_profiles_menu()
            self.statusBar().showMessage(f"Renamed profile to: {new_name}")
    
    def delete_profile(self):
        if self.current_profile == "Default":
            QMessageBox.warning(self, "Cannot Delete", 
                                "The default profile cannot be deleted.")
            return
        
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Are you sure you want to delete the profile '{self.current_profile}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.profiles[self.current_profile]
            self.current_profile = "Default"
            self.load_profile("Default")
            self.save_settings()
            self.update_profiles_menu()
            self.statusBar().showMessage(f"Deleted profile")
    
    def open_ollama_settings(self):
        dialog = OllamaSettingsDialog(self.base_url, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_url = dialog.get_url()
            if new_url and new_url != self.base_url:
                self.base_url = new_url
                self.save_settings()
                self.statusBar().showMessage(f"Ollama URL updated: {self.base_url}")
    
    def apply_theme(self, theme_name):
        if theme_name not in THEMES:
            return
        
        self.current_theme = theme_name
        theme = THEMES[theme_name]
        
        # Update theme actions
        for name, action in self.theme_actions.items():
            action.setChecked(name == theme_name)
        
        # Apply stylesheet
        stylesheet = f"""
            QWidget {{
                background-color: {theme['window_bg']};
                color: {theme['text_color']};
                font-family: Segoe UI, Arial;
            }}
            
            QGroupBox {{
                border: 1px solid {theme['border']};
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
            
            QTextEdit, QComboBox, QLineEdit {{
                background-color: {theme['base_bg']};
                border: 1px solid {theme['border']};
                border-radius: 3px;
                padding: 5px;
            }}
            
            QPushButton {{
                background-color: {theme['button_bg']};
                border: 1px solid {theme['border']};
                border-radius: 4px;
                padding: 5px 10px;
            }}
            
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            
            QProgressBar {{
                border: 1px solid {theme['border']};
                border-radius: 3px;
                text-align: center;
            }}
            
            QProgressBar::chunk {{
                background-color: {theme['progress_chunk']};
                width: 10px;
            }}
            
            QTextEdit#log_view {{
                font-family: 'Courier New', monospace;
                background-color: {theme['log_bg']};
                color: {theme['log_text']};
            }}
        """
        
        self.setStyleSheet(stylesheet)
        self.save_settings()
    
    def refresh_models(self):
        self.model_combo.clear()
        self.model_status.setText("Loading models...")
        self.refresh_btn.setEnabled(False)
        
        try:
            response = requests.get(f"{self.base_url.replace('/chat', '')}/tags", timeout=5)
            if response.status_code == 200:
                models = [model['name'] for model in response.json().get('models', [])]
                self.model_combo.addItems(models)
                self.model_status.setText(f"{len(models)} models loaded")
            else:
                self.model_status.setText(f"Error: {response.status_code}")
        except Exception as e:
            self.model_status.setText(f"Error: {str(e)}")
        finally:
            self.refresh_btn.setEnabled(True)
    
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select SRT File", "", "Subtitle Files (*.srt)"
        )
        if file_path:
            self.file_label.setText(f"File: {file_path}")
            self.selected_files = [file_path]
    
    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Folder with SRT Files")
        if folder_path:
            self.file_label.setText(f"Folder: {folder_path}")
            self.selected_files = self.find_srt_files(folder_path)
    
    def find_srt_files(self, folder_path):
        srt_files = []
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith('.srt'):
                    srt_files.append(os.path.join(root, file))
        return srt_files
    
    def start_translation(self):
        if not self.selected_files:
            QMessageBox.warning(self, "No Files", "Please select a file or folder first")
            return
        
        if not self.model_combo.currentText():
            QMessageBox.warning(self, "No Model", "Please select a model first")
            return
        
        # Get translation parameters
        target_lang = self.lang_combo.currentData()
        style = self.style_combo.currentText()
        model = self.model_combo.currentText()
        advanced_prompt = self.prompt_edit.toPlainText()
        
        # Create worker thread
        self.worker_thread = TranslationWorker(
            self.selected_files, target_lang, style, model, advanced_prompt, self.base_url
        )
        
        # Connect signals
        self.worker_thread.progress.connect(self.update_progress)
        self.worker_thread.log_message.connect(self.log_message)
        self.worker_thread.finished.connect(self.translation_finished)
        self.worker_thread.error.connect(self.show_error)
        
        # Update UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log_message("Starting translation...")
        
        # Start thread
        self.worker_thread.start()
    
    def cancel_translation(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.cancel()
            self.cancel_btn.setEnabled(False)
            self.log_message("Cancellation requested...")
    
    def translation_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.worker_thread = None
    
    def update_progress(self, current, total):
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
    
    def log_message(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {message}")
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )
        QApplication.processEvents()  # Ensure UI updates
    
    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)
        self.translation_finished()
    
    def clear_log(self):
        self.log_view.clear()
    
    def open_output_folder(self):
        if self.selected_files:
            output_dir = os.path.dirname(self.selected_files[0])
            os.startfile(output_dir)
    
    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.cancel()
            self.worker_thread.wait(2000)  # Wait up to 2 seconds
        
        self.save_profile()
        self.save_settings()
        event.accept()

# ======================
# APPLICATION START
# ======================
if __name__ == "__main__":
    app = QApplication([])
    app.setStyle(QStyleFactory.create("Fusion"))
    
    window = SRTTranslatorWindow()
    window.show()
    
    app.exec()
