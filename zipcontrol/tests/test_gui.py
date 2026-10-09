import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QEvent, Qt, qInstallMessageHandler
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from zipcontrol.bridge import Frame
from zipcontrol.control import Controller, Stick
from zipcontrol.gui import Preview, Window, configure_application


def test_gui_passes_shared_drag_size_to_ai_mission_without_touching_phone(monkeypatch):
    import zipcontrol.flight_gui as module

    app = QApplication.instance() or QApplication([])
    starts = []

    class FakeMission:
        busy = False

        def __init__(self, *args, **kwargs):
            self.settings = kwargs

        def start(self, require_ui):
            starts.append((self.settings["drag_strength"], require_ui))

    monkeypatch.setattr(module, "Astra", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(module, "Mission", FakeMission)
    panel = module.FlightPanel(
        SimpleNamespace(
            bridge=SimpleNamespace(latest_frame=lambda: SimpleNamespace(width=120, height=100)),
            release=lambda: None,
        )
    )
    try:
        panel.roi = [0, 0, 120, 40]
        panel.goal.setPlainText("inspect")
        panel.start()
        panel.manual_strength.setValue(55)
        panel.start()
        assert starts == [(1.0, False), (0.55, False)]
    finally:
        panel.close()
        app.processEvents()


def test_gui_holds_releases_on_deactivation_and_invalidates_on_session_change():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = Window()
    writes = []
    controller = Controller(writes.append)
    controller.geometry(800, 1200)
    controller.calibrate(Stick(200, 800, 100), Stick(600, 800, 100), controller.epoch)
    frame = Frame(np.zeros((1200, 800, 3), dtype=np.uint8), 1, time.monotonic(), 0, 0, 1)
    bridge = SimpleNamespace(
        error=None,
        controller=controller,
        latest_frame=lambda: frame,
        set_sticks=controller.set_sticks,
        release_all=controller.release_all,
        close=controller.close,
        transport=SimpleNamespace(device_name="TEST"),
        fps=30,
    )
    window.bridge = bridge
    window.show()
    window.tick()
    try:
        assert window.hold_button.isEnabled()
        QTest.mousePress(window.hold_button, Qt.MouseButton.LeftButton)
        window.tick()
        assert len(controller.active) == 2
        app.sendEvent(window, QEvent(QEvent.Type.ApplicationDeactivate))
        assert not window.holding and not controller.active
        QTest.mouseRelease(window.hold_button, Qt.MouseButton.LeftButton)
        controller.geometry(1200, 800)
        frame = Frame(np.zeros((800, 1200, 3), dtype=np.uint8), 2, time.monotonic(), 0, 0, 2)
        window.tick()
        assert not window.hold_button.isEnabled()
        assert window.preview.sticks is None
    finally:
        window.close()
        app.processEvents()


def test_background_worker_delivers_to_gui():
    app = QApplication.instance() or QApplication([])
    window = Window()
    assert window.simulation_panel.view.status() == QQuickWidget.Status.Ready
    received = []
    try:
        window.work(lambda: 42, received.append)
        deadline = time.monotonic() + 3
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert received == [42] and not window.busy
    finally:
        window.close()
        app.processEvents()


def test_mac_deactivation_keeps_ai_mission_running_but_esc_stops_it():
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.timer.stop()
    stopped = []
    runner = SimpleNamespace(running=True)

    def stop(reason):
        stopped.append(reason)
        runner.running = False

    window.flight.mission = SimpleNamespace(executor=runner, busy=False, stop=stop)
    try:
        window.eventFilter(window, QEvent(QEvent.Type.ApplicationDeactivate))
        assert runner.running and not stopped
        QTest.keyClick(window, Qt.Key.Key_Escape)
        assert not runner.running and stopped
        assert not window.flight.observe_only.isChecked()
    finally:
        window.close()
        app.processEvents()


def test_preview_renders_readonly_rgb_with_padded_scanlines():
    app = QApplication.instance() or QApplication([])
    preview = Preview()
    preview.resize(405, 640)
    # Match the device's 810x1280 geometry with padding between rows, as in FFmpeg output.
    storage = np.zeros((1280, 816, 3), dtype=np.uint8)
    rgb = storage[:, :810, :]
    rgb[:] = (30, 140, 210)
    rgb.flags.writeable = False
    assert not rgb.flags.c_contiguous
    preview.frame = Frame(rgb, 1, 0, 0, 0, 1)
    try:
        preview.show()
        app.processEvents()
        image = preview.grab().toImage()
        assert image.pixelColor(image.width() // 2, image.height() // 2).getRgb() == (30, 140, 210, 255)
        # A second paint proves that the first left no active painter on the backing store.
        preview.frame = Frame(np.full((1280, 810, 3), 180, dtype=np.uint8), 2, 0, 0, 0, 1)
        image = preview.grab().toImage()
        assert image.pixelColor(image.width() // 2, image.height() // 2).getRgb() == (180, 180, 180, 255)
    finally:
        preview.close()
        app.processEvents()


def test_preview_releases_painter_after_draw_exception(monkeypatch):
    app = QApplication.instance() or QApplication([])
    preview = Preview()
    errors, messages = [], []
    original_paint = preview._paint

    def fail_once(_):
        preview._paint = original_paint
        raise RuntimeError("injected paint failure")

    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args[1]))
    previous = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    try:
        preview._paint = fail_once
        preview.show()
        app.processEvents()
        preview.grab()
        assert len(errors) == 1 and "injected paint failure" in str(errors[0])
        assert not any("active painter" in m or "one painter at a time" in m for m in messages)
    finally:
        qInstallMessageHandler(previous)
        preview.close()
        app.processEvents()
