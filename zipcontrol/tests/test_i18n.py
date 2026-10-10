import ast
import os
import re
from pathlib import Path
from string import Formatter
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from test_guidance import Sequence, mission

from zipcontrol.actions import ActionAdapter, Subgoal
from zipcontrol.gui import Window
from zipcontrol.i18n import ENGLISH, SettingsStore, error_text, message, translate


def test_catalog_covers_ui_templates_and_preserves_format_fields():
    root = Path(__file__).parents[1] / "src/zipcontrol"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "m"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            source = node.args[0].value
            if re.search("[가-힣]", source):
                assert source in ENGLISH, (path.name, source)

    def fields(text):
        return {(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(text) if name}

    for source, english in ENGLISH.items():
        assert not re.search("[가-힣]", english)
        assert fields(source) == fields(english), source


def test_nested_messages_translate_labels_without_changing_user_content():
    goal = "왼쪽으로 이동 {user input}"
    text = message("현재 목표: {p0}\n완료 조건: {p1}", p0=goal, p1="원본 사용자 조건")
    assert translate(text, "en") == "Current subgoal: " + goal + "\nCompletion criteria: 원본 사용자 조건"
    status = message("저장: ") + "/tmp/한국어 폴더/data.json"
    assert translate(status, "en") == "Saved: /tmp/한국어 폴더/data.json"
    error = ValueError(message("최신 화면이 필요합니다."))
    assert translate("error: " + error_text(error), "en") == "error: A fresh frame is required."


def test_language_preferences_persist_and_invalid_files_fall_back_to_english(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load_language() == "en"
    store.save_language("ko")
    assert SettingsStore(store.path).load_language() == "ko"
    with pytest.raises(ValueError):
        store.save_language("bad")
    assert store.load_language() == "ko"
    for invalid in ("[]", "{broken", '{"version":1,"language":"xx"}', '{"version":2,"language":"ko"}'):
        store.path.write_text(invalid)
        assert store.load_language() == "en"


def test_ui_switch_preserves_goal_controls_and_active_mission(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    window = Window(settings_path=settings)
    window.timer.stop()
    calls = []
    running = SimpleNamespace(executor=SimpleNamespace(running=True), busy=True, stop=calls.append)
    original_goal = "한국어 목표를 그대로 보존 {x}"
    try:
        assert window.tabs.tabText(2) == "Options"
        assert window.tabs.tabText(1) == "AI Mission"
        for widget in window.findChildren(QLabel) + window.findChildren(QPushButton):
            assert not re.search("[가-힣]", widget.text()), widget.text()
        window.flight.goal.setPlainText(original_goal)
        window.flight.manual_strength.setValue(55)
        window.flight.observe_only.setChecked(True)
        window.flight.mission = running
        window.language_combo.setCurrentIndex(1)
        assert window.tabs.tabText(2) == "옵션"
        assert "초록" in window.simulation_panel.scene_state.legend
        assert SettingsStore(settings).load_language() == "ko"
        window.language_combo.setCurrentIndex(0)
        assert window.tabs.tabText(2) == "Options"
        assert window.flight.goal.toPlainText() == original_goal
        assert window.flight.manual_strength.value() == 55
        assert window.flight.observe_only.isChecked()
        assert window.flight.mission is running and not calls
        assert "Green:" in window.simulation_panel.scene_state.legend
        assert window.simulation_panel.simulation.deadline == 0
        assert window.command_stream.sequence == 0
    finally:
        window.flight.mission = None
        window.close()
        app.processEvents()
    reopened = Window(settings_path=settings)
    try:
        assert reopened.i18n.language == "en"
    finally:
        reopened.close()


def test_language_save_failure_keeps_previous_ui_and_setting(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(settings_path=tmp_path / "settings.json")

    def fail(_):
        raise OSError("disk unavailable")

    monkeypatch.setattr(window.settings_store, "save_language", fail)
    try:
        window.language_combo.setCurrentIndex(1)
        assert window.i18n.language == "en" and window.language_combo.currentData() == "en"
        assert window.language_status.text() == "Could not save language preference: disk unavailable"
    finally:
        window.close()
        app.processEvents()


def test_english_mission_requests_english_and_keeps_control_vectors(tmp_path):
    goal = "왼쪽으로 이동"
    m = mission(tmp_path, Sequence(), mode="direct", language="en")
    m.executor.running = True
    m.executor.epoch = 1
    observation = m._observation()
    assert observation.metadata["response_language"] == "English"
    assert "latest camera image" in observation.metadata["current_subgoal"]["completion_criteria"]
    english = ActionAdapter.command("YAW_LEFT", "obs", Subgoal.direct(goal, "en"), language="en")
    korean = ActionAdapter.command("YAW_LEFT", "obs", Subgoal.direct(goal), language="ko")
    assert english["reason"] == "Turn left · " + goal
    for key in ("left_xy", "right_xy", "valid_for_ms", "observation_id"):
        assert english[key] == korean[key]
