"""Explicit locale and lossless message templates; never translate user input."""

import json
import os
import tempfile
from pathlib import Path

LANGUAGES = ("en", "ko")
ENGLISH = json.loads((Path(__file__).parent / "locales/en.json").read_text())


class Message(str):
    def __new__(cls, source, **values):
        value = str.__new__(cls, source.format(**values) if values else source)
        value.source, value.values = source, values
        return value

    def render(self, language):
        source = ENGLISH.get(self.source, self.source) if language == "en" else self.source
        values = {
            key: translate(value, language) if isinstance(value, Message) else value
            for key, value in self.values.items()
        }
        return source.format(**values) if values else source

    def __add__(self, other):
        return Message("{left}{right}", left=self, right=other)

    def __radd__(self, other):
        return Message("{left}{right}", left=other, right=self)


def message(source, **values):
    return Message(source, **values)


def translate(value, language="ko"):
    if isinstance(value, Message):
        return value.render(language)
    return ENGLISH.get(value, value) if language == "en" and isinstance(value, str) else value


def error_text(error):
    return error.args[0] if len(error.args) == 1 and isinstance(error.args[0], Message) else str(error)


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path.cwd() / ".runtime/settings.json"

    def load_language(self):
        try:
            data = json.loads(self.path.read_text())
            language = data.get("language")
            return language if data.get("version") == 1 and language in LANGUAGES else "en"
        except (OSError, ValueError, TypeError, AttributeError):
            return "en"

    def save_language(self, language):
        if language not in LANGUAGES:
            raise ValueError("Unsupported language")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False) as f:
                temporary = Path(f.name)
                json.dump({"version": 1, "language": language}, f)
                f.flush()
                os.fsync(f.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
