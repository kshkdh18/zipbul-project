import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from zipcontrol.bridge import Frame
from zipcontrol.calibration import CalibrationStore
from zipcontrol.control import Controller, Stick
from zipcontrol.gui import Window


def test_profiles_survive_restart_and_never_cross_device_or_geometry(tmp_path):
    path = tmp_path / "calibration.json"
    expected = (Stick(200.25, 800.5, 50.75), Stick(600.25, 800.5, 55.25))
    CalibrationStore(path).save("phone-a", 800, 1200, *expected)
    CalibrationStore(path).save("phone-b", 800, 1200, Stick(180, 750, 40), Stick(650, 750, 40))
    store = CalibrationStore(path)
    assert store.load("phone-a", 800, 1200) == expected
    assert store.load("phone-a", 1200, 800) is None
    assert store.load("another-phone", 800, 1200) is None


def test_corrupt_file_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text("{broken")
    store = CalibrationStore(path)
    with pytest.raises(ValueError):
        store.load("phone", 800, 1200)
    with pytest.raises(ValueError):
        store.save("phone", 800, 1200, Stick(200, 800, 40), Stick(600, 800, 40))
    assert path.read_text() == "{broken"


@pytest.mark.parametrize("radius", [-10, 10000, float("nan")])
def test_invalid_saved_circle_never_loads(tmp_path, radius):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "devices": {
                    "phone": {
                        "800x1200": {
                            "left": {"x": 200, "y": 800, "radius": radius},
                            "right": {"x": 600, "y": 800, "radius": 40},
                        }
                    }
                },
            }
        )
    )
    with pytest.raises(ValueError):
        CalibrationStore(path).load("phone", 800, 1200)


def test_manual_gui_calibration_is_restored_on_new_connection_without_touch_commands(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "calibration.json"
    frame = Frame(np.zeros((1200, 800, 3), dtype=np.uint8), 1, 0, 0, 0, 1)
    writes = []

    def bridge():
        c = Controller(writes.append)
        c.geometry(800, 1200)
        return SimpleNamespace(
            adb=SimpleNamespace(serial="phone"),
            controller=c,
            latest_frame=lambda: frame,
            release_all=c.release_all,
            close=c.close,
            calibrate=lambda left, right, f: c.calibrate(left, right, f.epoch),
        )

    first = Window(calibration_path=path, settings_path=tmp_path / "settings.json")
    first.i18n.set_language("ko")
    try:
        first.connected(bridge())
        first.preview.frame = frame
        first.begin_calibration()
        for point in [(200, 800), (245, 800), (600, 800), (650, 800)]:
            first.select_point(*point)
        assert path.exists()
        assert "저장 완료" in first.instructions.text()
    finally:
        first.close()
    second = Window(calibration_path=path, settings_path=tmp_path / "settings.json")
    second.i18n.set_language("ko")
    try:
        second.connected(bridge())
        assert second.bridge.controller.sticks == (Stick(200, 800, 45), Stick(600, 800, 50))
        assert second.bridge.controller.active == {}
        assert second.bridge.controller.deadline == 0
        assert writes == []
        assert "불러왔습니다" in second.instructions.text()
    finally:
        second.close()
        app.processEvents()
