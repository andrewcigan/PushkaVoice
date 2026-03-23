import json
import os
from pathlib import Path

DEFAULT_SETTINGS = {
    "hotkey": "<cmd>+<shift>+d",
    "microphone_device_id": None,
    "indicator_mode": "menubar",
    "save_dictations": True,
    "dictations_folder": str(Path(__file__).parent.parent / "dictations"),
    "auto_paste": True,
    "sample_rate": 16000,
    "llm_cleanup": True,
}

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"


class Config:
    def __init__(self):
        self._data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self._data.update(saved)

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    @property
    def hotkey(self):
        return self._data["hotkey"]

    @property
    def microphone_device_id(self):
        return self._data["microphone_device_id"]

    @property
    def dictations_folder(self):
        path = Path(self._data["dictations_folder"]).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @property
    def auto_paste(self):
        return self._data["auto_paste"]

    @property
    def sample_rate(self):
        return self._data["sample_rate"]
