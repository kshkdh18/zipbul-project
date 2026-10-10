from __future__ import annotations

import math
import signal
import sys
import threading
import time

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .bridge import Bridge
from .calibration import CalibrationStore
from .camera import crop_frame
from .control import Stick
from .execution import CommandStream
from .i18n import SettingsStore, error_text
from .i18n import message as m
from .lab import TouchLab, calibrate_lab
from .localized_ui import I18n
from .sim_view import SimulationPanel
from .validation import output_directory


def image_rect(widget_width, widget_height, image_width, image_height):
    scale = min(widget_width / image_width, widget_height / image_height)
    w, h = image_width * scale, image_height * scale
    return (widget_width - w) / 2, (widget_height - h) / 2, w, h


def map_to_image(x, y, widget_width, widget_height, image_width, image_height):
    rx, ry, rw, rh = image_rect(widget_width, widget_height, image_width, image_height)
    if not (rx <= x < rx + rw and ry <= y < ry + rh):
        return None
    return (x - rx) * image_width / rw, (y - ry) * image_height / rh


class Preview(QWidget):
    selected = Signal(float, float)

    def __init__(self, i18n=None):
        super().__init__()
        self.i18n = i18n or I18n(parent=self)
        self.i18n.changed.connect(self.update)
        self.setMinimumSize(380, 480)
        self.frame = None
        self.sticks = None
        self.points = []
        self.camera_rect = None
        self.requested_targets = []

    def paintEvent(self, _):
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            # Qt reuses the backing store; an exception must not leave it being painted.
            painter.end()

    def _paint(self, painter):
        painter.fillRect(self.rect(), QColor("#080f19"))
        if self.frame is None:
            painter.setPen(QColor("#8191a9"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, self.i18n.render(m("USB로 휴대폰을 연결하세요"))
            )
            return
        f = self.frame
        # Also accept externally supplied Frames backed by sliced/padded arrays.
        # Keep rgb alive until drawImage finishes. This is zero-copy for bridge frames.
        rgb = np.ascontiguousarray(f.rgb)
        image = QImage(rgb.data, f.width, f.height, rgb.strides[0], QImage.Format.Format_RGB888)
        rect = QRectF(*image_rect(self.width(), self.height(), f.width, f.height))
        painter.drawImage(rect, image)
        scale = rect.width() / f.width
        if self.camera_rect:
            r = self.camera_rect
            painter.setPen(QPen(QColor("#f2bc57"), 1))
            painter.drawRect(
                QRectF(
                    rect.x() + r.x() * scale, rect.y() + r.y() * scale, r.width() * scale, r.height() * scale
                )
            )
        for i, s in enumerate(self.sticks or []):
            painter.setPen(QPen(QColor("#3ae1bf" if i == 0 else "#76a8ff"), 2))
            center = QPointF(rect.x() + s.x * scale, rect.y() + s.y * scale)
            painter.drawEllipse(center, s.radius * scale, s.radius * scale)
            painter.drawText(center, " L" if i == 0 else " R")
            if i < len(self.requested_targets) and self.requested_targets[i] is not None:
                x, y = self.requested_targets[i]
                target = QPointF(rect.x() + x * scale, rect.y() + y * scale)
                painter.setPen(QPen(QColor("#ffcb5b"), 2, Qt.PenStyle.DashLine))
                painter.drawLine(center, target)
                painter.setPen(QPen(QColor("#ffcb5b"), 2))
                painter.drawEllipse(target, 4, 4)
                painter.drawText(target + QPointF(6, -6), self.i18n.render(m("요청")))
        painter.setPen(QPen(QColor("#ffbd54"), 3))
        for x, y in self.points:
            painter.drawEllipse(QPointF(rect.x() + x * scale, rect.y() + y * scale), 5, 5)

    def mousePressEvent(self, event):
        if self.frame and event.button() == Qt.MouseButton.LeftButton:
            point = map_to_image(
                event.position().x(),
                event.position().y(),
                self.width(),
                self.height(),
                self.frame.width,
                self.frame.height,
            )
            if point:
                self.selected.emit(*point)


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(object)


class Window(QMainWindow):
    def __init__(self, serial=None, server_path=None, calibration_path=None, settings_path=None):
        super().__init__()
        self.settings_store = SettingsStore(settings_path)
        self.i18n = I18n(self.settings_store.load_language(), self)
        self.serial, self.server_path = serial, server_path
        self.calibration_store = CalibrationStore(calibration_path)
        self.bridge = None
        self.lab = None
        self.busy = False
        self.closing = False
        self.holding = False
        self.demo_started = None
        self.calibrating = False
        self.calibration_epoch = None
        self.display_epoch = None
        self.last_sequence = 0
        self.output = output_directory("gui")
        self.workers = []
        self.i18n.set(self, "setWindowTitle", m("Zipcontrol · Astra + Luna 이동 가이드"))
        self.resize(1500, 920)
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        self.command_stream = CommandStream()
        split = QSplitter(Qt.Orientation.Horizontal)
        row.addWidget(split)
        videos = QWidget()
        video_layout = QVBoxLayout(videos)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.addWidget(self.i18n.widget(QLabel, m("Android 화면 · 영역 선택 / 조이스틱 보정")))
        self.preview = Preview(self.i18n)
        self.preview.setMinimumSize(260, 300)
        self.preview.selected.connect(self.select_point)
        video_layout.addWidget(self.preview, 3)
        crop_title = self.i18n.widget(QLabel, m("AI가 보는 영상"))
        crop_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #60e5c3; padding-top: 8px")
        video_layout.addWidget(crop_title)
        self.camera_preview = Preview(self.i18n)
        self.camera_preview.setMinimumSize(260, 180)
        video_layout.addWidget(self.camera_preview, 2)
        split.addWidget(videos)
        self.simulation_panel = SimulationPanel(self.command_stream, self.i18n)
        split.addWidget(self.simulation_panel)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(390)
        split.addWidget(self.tabs)
        split.setSizes([340, 710, 400])
        lab_panel = QWidget()
        panel = QVBoxLayout(lab_panel)
        lab_scroll = QScrollArea()
        lab_scroll.setWidgetResizable(True)
        lab_scroll.setWidget(lab_panel)
        self.i18n.tab(self.tabs, lab_scroll, m("연결 / 터치 실험"))
        title = self.i18n.widget(QLabel, m("ZIPCONTROL\nAstra + Luna 이동 가이드"))
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #eef4ff; margin-bottom: 12px")
        panel.addWidget(title)
        note = self.i18n.widget(
            QLabel,
            m("USB 화면과 실제 Android 터치를 연결합니다.\n드론을 손으로 움직이며 이동 지시를 따라가세요."),
        )
        note.setStyleSheet("color: #ffc77b; font-size: 12px")
        panel.addWidget(note)
        self.connection_mode = QComboBox()
        self.i18n.items(self.connection_mode, [m("AI 전용 서버"), m("기존 scrcpy · 터치 실험")])
        panel.addWidget(self.connection_mode)
        self.connect_button = self.i18n.widget(QPushButton, m("USB 연결"))
        self.connect_button.clicked.connect(self.toggle_connection)
        panel.addWidget(self.connect_button)
        self.lab_button = self.i18n.widget(QPushButton, m("휴대폰 테스트 화면 열기 + 자동 보정"))
        self.lab_button.clicked.connect(self.open_lab)
        panel.addWidget(self.lab_button)
        self.calibrate_button = self.i18n.widget(QPushButton, m("현재 화면에서 조이스틱 보정"))
        self.calibrate_button.clicked.connect(self.begin_calibration)
        panel.addWidget(self.calibrate_button)
        self.import_button = self.i18n.widget(QPushButton, m("기존 L/R 보정 가져오기…"))
        self.import_button.clicked.connect(self.import_calibration)
        panel.addWidget(self.import_button)
        self.instructions = self.i18n.widget(
            QLabel, m("USB 연결 후 기존 보정을 가져오거나 L/R 위치를 지정하세요.")
        )
        self.instructions.setWordWrap(True)
        self.instructions.setFixedWidth(355)
        panel.addWidget(self.instructions)
        self.groups = []
        self.axes = []
        self.contacts = []
        for label in ("LEFT", "RIGHT"):
            group = self.i18n.widget(QGroupBox, label)
            box = QVBoxLayout(group)
            contact = self.i18n.widget(QCheckBox, m("접촉 유지"))
            contact.setChecked(True)
            box.addWidget(contact)
            axes = []
            for axis in (m("X · 좌우"), m("Y · 상하 (+는 아래)")):
                line = QHBoxLayout()
                line.addWidget(self.i18n.widget(QLabel, axis))
                spin = QDoubleSpinBox()
                spin.setRange(-1, 1)
                spin.setSingleStep(0.1)
                spin.setDecimals(2)
                spin.setValue(0.2 if label == "LEFT" else -0.2)
                line.addWidget(spin)
                axes.append(spin)
                box.addLayout(line)
            panel.addWidget(group)
            self.groups.append(group)
            self.axes.append(axes)
            self.contacts.append(contact)
        self.hold_button = self.i18n.widget(QPushButton, m("누르는 동안 두 스틱 입력"))
        self.hold_button.pressed.connect(self.hold)
        self.hold_button.released.connect(self.release)
        panel.addWidget(self.hold_button)
        self.demo_button = self.i18n.widget(QPushButton, m("목표 위치로 동시 드래그 · 1초"))
        self.demo_button.clicked.connect(self.demo)
        panel.addWidget(self.demo_button)
        self.release_button = self.i18n.widget(QPushButton, m("전체 터치 해제  [Esc]"))
        self.release_button.setStyleSheet("background: #8d3545; color: white; font-weight: bold")
        self.release_button.clicked.connect(self.release)
        panel.addWidget(self.release_button)
        self.capture_button = self.i18n.widget(QPushButton, m("현재 프레임 저장"))
        self.capture_button.clicked.connect(self.capture)
        panel.addWidget(self.capture_button)
        panel.addStretch()
        self.stats = self.i18n.widget(QLabel, m("연결 대기"))
        self.stats.setWordWrap(True)
        self.stats.setFixedWidth(355)
        panel.addWidget(self.stats)
        self.status = self.i18n.widget(QLabel, "")
        self.status.setWordWrap(True)
        self.status.setFixedWidth(355)
        panel.addWidget(self.status)
        from .flight_gui import FlightPanel

        self.flight = FlightPanel(self)
        flight_scroll = QScrollArea()
        flight_scroll.setWidgetResizable(True)
        flight_scroll.setWidget(self.flight)
        self.i18n.tab(self.tabs, flight_scroll, m("AI 목표 수행"))
        self.add_options_tab()
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.refresh_buttons()

    def add_options_tab(self):
        options = QWidget()
        layout = QVBoxLayout(options)
        label = self.i18n.widget(QLabel, m("언어"))
        layout.addWidget(label)
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("한국어", "ko")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.i18n.language))
        layout.addWidget(self.language_combo)
        note = self.i18n.widget(
            QLabel,
            m(
                "화면 언어는 즉시 바뀌며 다음 실행에도 유지됩니다. AI 설명은 다음 임무부터 선택한 언어를 사용합니다."
            ),
        )
        note.setWordWrap(True)
        note.setFixedWidth(355)
        layout.addWidget(note)
        self.language_status = self.i18n.widget(QLabel, "")
        self.language_status.setWordWrap(True)
        self.language_status.setFixedWidth(355)
        layout.addWidget(self.language_status)
        layout.addStretch()
        self.i18n.tab(self.tabs, options, m("옵션"))
        self.language_combo.currentIndexChanged.connect(self.change_language)

    def change_language(self, _index):
        language = self.language_combo.currentData()
        try:
            self.settings_store.save_language(language)
        except OSError as exc:
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(self.language_combo.findData(self.i18n.language))
            self.language_combo.blockSignals(False)
            self.i18n.set(
                self.language_status, "setText", m("언어 설정을 저장하지 못했습니다: ") + error_text(exc)
            )
            return
        self.i18n.set_language(language)
        self.i18n.set(self.language_status, "setText", m("언어 설정을 저장했습니다."))

    def work(self, fn, callback):
        self.busy = True
        self.refresh_buttons()
        signals = WorkerSignals()

        def success(value):
            self.busy = False
            if self.closing:
                if hasattr(value, "close"):
                    value.close()
                QTimer.singleShot(0, self.close)
                return
            callback(value)
            self.refresh_buttons()

        def failure(message):
            self.busy = False
            self.i18n.set(self.status, "setText", message)
            self.refresh_buttons()
            if self.closing:
                QTimer.singleShot(0, self.close)

        signals.done.connect(success)
        signals.failed.connect(failure)

        def runner():
            try:
                signals.done.emit(fn())
            except Exception as exc:
                signals.failed.emit(error_text(exc))

        thread = threading.Thread(target=runner, daemon=True)
        self.workers.append((signals, thread))
        thread.start()

    def toggle_connection(self):
        if self.bridge:
            self.flight.stop("disconnected")
            self.release()
            bridge, lab = self.bridge, self.lab
            self.bridge = self.lab = None
            self.preview.frame = None
            self.preview.sticks = None

            def close():
                bridge.close()
                if lab:
                    lab.close()

            self.work(close, lambda _: self.i18n.set(self.status, "setText", m("연결 종료")))
        else:
            self.i18n.set(self.status, "setText", m("scrcpy 4.1 전용 세션을 연결하는 중…"))
            from .guard import GuardBridge

            cls = GuardBridge if self.connection_mode.currentIndex() == 0 else Bridge
            self.work(lambda: cls(self.serial, self.server_path).connect(), self.connected)

    def connected(self, bridge):
        self.bridge = bridge
        self.last_sequence = 0
        self.display_epoch = None
        self.i18n.set(self.status, "setText", m("화면 수신 중 · 입력은 보정 후 활성화됩니다."))
        self.i18n.set(self.instructions, "setText", m("수동 보정이 끝나면 기본값으로 자동 저장됩니다."))
        frame = bridge.latest_frame()
        if frame is not None:
            try:
                sticks = self.calibration_store.load(bridge.adb.serial, frame.width, frame.height)
                if sticks is not None:
                    bridge.calibrate(*sticks, frame)
                    self.i18n.set(
                        self.instructions,
                        "setText",
                        m("저장된 L/R 기본 보정을 불러왔습니다. 현재 화면의 스틱 위치와 맞는지 확인하세요."),
                    )
                    self.i18n.set(self.status, "setText", m("기본값: ") + str(self.calibration_store.path))
            except (OSError, ValueError, RuntimeError) as exc:
                self.i18n.set(
                    self.status,
                    "setText",
                    m("기본 보정을 불러오지 못했습니다. 수동 보정하세요: ") + error_text(exc),
                )
        self.flight.connected()

    def import_calibration(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.i18n.render(m("L/R 보정 가져오기")), "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            frame = self.bridge.latest_frame()
            sticks = CalibrationStore(path).load(self.bridge.adb.serial, frame.width, frame.height)
            if sticks is None:
                raise ValueError(m("현재 기기·화면 크기와 일치하는 보정이 없습니다."))
            self.bridge.calibrate(*sticks, frame)
            self.calibration_store.save(self.bridge.adb.serial, frame.width, frame.height, *sticks)
            self.i18n.set(self.status, "setText", m("기존 L/R 보정을 가져왔습니다."))
        except (ValueError, RuntimeError, OSError) as exc:
            self.i18n.set(self.status, "setText", error_text(exc))

    def open_lab(self):
        self.release()
        bridge = self.bridge
        self.calibrating = False
        self.i18n.set(self.status, "setText", m("휴대폰 Chrome에서 테스트 화면을 여는 중…"))

        def setup():
            if self.lab is None:
                self.lab = TouchLab(bridge.adb, self.output).start()
            self.lab.open_phone()
            return calibrate_lab(bridge, self.lab)

        def ready(_):
            self.i18n.set(
                self.instructions,
                "setText",
                m("테스트 화면 보정 완료. 두 스틱의 목표 위치를 정한 뒤 입력하세요."),
            )
            self.i18n.set(
                self.status,
                "setText",
                m("Android 실제 터치 이벤트를 ") + str(self.output) + m("에 기록합니다."),
            )

        self.work(setup, ready)

    def begin_calibration(self):
        self.release()
        self.bridge.controller.sticks = None
        self.calibrating = True
        self.calibration_epoch = self.preview.frame.epoch
        self.preview.points = []
        self.i18n.set(self.instructions, "setText", m("1/4 · 왼쪽 조이스틱 중심을 클릭하세요."))

    def select_point(self, x, y):
        if self.flight.point(x, y):
            return
        if not self.calibrating:
            return
        if self.preview.frame.epoch != self.calibration_epoch:
            self.calibrating = False
            self.i18n.set(self.instructions, "setText", m("화면이 변경되었습니다. 다시 보정하세요."))
            return
        self.preview.points.append((x, y))
        prompts = [
            "",
            m("2/4 · 왼쪽 조이스틱의 이동 한계점을 클릭하세요."),
            m("3/4 · 오른쪽 조이스틱 중심을 클릭하세요."),
            m("4/4 · 오른쪽 조이스틱의 이동 한계점을 클릭하세요."),
        ]
        if len(self.preview.points) < 4:
            self.i18n.set(self.instructions, "setText", prompts[len(self.preview.points)])
        else:
            p = self.preview.points
            try:
                left = Stick(*p[0], math.dist(p[0], p[1]))
                right = Stick(*p[2], math.dist(p[2], p[3]))
                self.bridge.calibrate(left, right, self.preview.frame)
                self.i18n.set(
                    self.instructions, "setText", m("보정 완료. X는 오른쪽, Y는 아래쪽이 양수입니다.")
                )
                try:
                    self.calibration_store.save(
                        self.bridge.adb.serial,
                        self.preview.frame.width,
                        self.preview.frame.height,
                        left,
                        right,
                    )
                    self.i18n.set(
                        self.instructions,
                        "setText",
                        m("L/R 기본 보정 저장 완료. 다음 연결에서 같은 기기·화면 크기일 때 자동 적용됩니다."),
                    )
                    self.i18n.set(self.status, "setText", m("저장: ") + str(self.calibration_store.path))
                except (OSError, ValueError) as exc:
                    self.i18n.set(
                        self.status,
                        "setText",
                        m("현재 보정은 적용됐지만 기본값 저장에 실패했습니다: ") + error_text(exc),
                    )
            except Exception as exc:
                self.i18n.set(self.status, "setText", error_text(exc))
            self.calibrating = False
            self.preview.points = []
        self.preview.update()

    def targets(self, scale=1):
        return [
            tuple(v.value() * scale for v in axes) if contact.isChecked() else None
            for axes, contact in zip(self.axes, self.contacts, strict=True)
        ]

    def hold(self):
        self.demo_started = None
        self.holding = True

    def demo(self):
        self.holding = False
        self.demo_started = time.monotonic()

    def release(self):
        if hasattr(self, "flight"):
            self.flight.stop("user_released")
        self.holding = False
        self.demo_started = None
        if self.bridge:
            try:
                self.bridge.release_all()
            except Exception as exc:
                self.i18n.set(self.status, "setText", error_text(exc))

    def capture(self):
        from PIL import Image

        frame = self.bridge.latest_frame()
        if frame:
            self.output.mkdir(parents=True, exist_ok=True)
            path = self.output / f"frame-{frame.sequence}.png"
            Image.fromarray(frame.rgb).save(path)
            self.i18n.set(self.status, "setText", m("저장: ") + str(path.resolve()))

    def refresh_buttons(self):
        connected = bool(self.bridge and not self.bridge.error)
        calibrated = connected and self.bridge.controller.sticks is not None
        self.i18n.set(self.connect_button, "setText", m("연결 종료") if self.bridge else m("USB 연결"))
        flight_busy = hasattr(self, "flight") and self.flight.busy
        self.connect_button.setEnabled(not self.busy and not flight_busy)
        self.connection_mode.setEnabled(not self.busy and not self.bridge and not flight_busy)
        for button in (self.lab_button, self.calibrate_button, self.capture_button, self.import_button):
            button.setEnabled(
                connected and not self.busy and not flight_busy and self.preview.frame is not None
            )
        for button in (self.hold_button, self.demo_button):
            # The guarded connection exposes manual axis checks in the AI tab instead.
            guarded = hasattr(self.bridge, "guard")
            button.setEnabled(
                calibrated and not self.busy and not self.calibrating and not flight_busy and not guarded
            )
        self.release_button.setEnabled(bool(self.bridge))

    def tick(self):
        self.flight.tick()
        if self.bridge:
            b = self.bridge
            frame = b.latest_frame()
            if frame and frame.sequence != self.last_sequence:
                if self.display_epoch is not None and self.display_epoch != frame.epoch:
                    self.flight.stop("geometry_changed")
                    self.flight.profile = None
                    self.flight.roi_points = None
                    self.flight.roi = None
                    self.camera_preview.frame = None
                    self.preview.camera_rect = None
                    self.holding = False
                    self.demo_started = None
                    self.calibrating = False
                    self.preview.points = []
                    self.i18n.set(
                        self.instructions, "setText", m("화면 크기/세션이 변경되었습니다. 다시 보정하세요.")
                    )
                self.display_epoch = frame.epoch
                self.last_sequence = frame.sequence
                self.preview.frame = frame
            self.preview.sticks = b.controller.sticks
            if b.error:
                self.holding = False
                self.demo_started = None
                self.i18n.set(self.status, "setText", m("연결 오류 · 재연결 필요: ") + b.error)
            try:
                if self.holding:
                    b.set_sticks(*self.targets())
                elif self.demo_started is not None:
                    elapsed = time.monotonic() - self.demo_started
                    if elapsed >= 1:
                        self.release()
                    else:
                        b.set_sticks(*self.targets(min(1, elapsed / 0.3)))
            except Exception as exc:
                self.release()
                self.i18n.set(self.status, "setText", error_text(exc))
            if frame:
                guard_state = b.guard.snapshot() if getattr(b, "guard", None) else None
                touches = guard_state["active"] if guard_state else len(b.controller.active)
                reason = guard_state["reason"] if guard_state else b.controller.last_reason
                source = m("Android 보고") if guard_state else m("송신 측")
                self.i18n.set(
                    self.stats,
                    "setText",
                    m(
                        "{p0} · {p1}×{p2}\n{p3:.1f} fps · 마지막 프레임 {p4:.2f}s 전\n{p5} 활성 접촉 {p6} · {p7}",
                        p0=b.transport.device_name,
                        p1=frame.width,
                        p2=frame.height,
                        p3=b.fps,
                        p4=time.monotonic() - frame.received_at,
                        p5=source,
                        p6=touches,
                        p7=reason,
                    ),
                )
        frame = self.bridge.latest_frame() if self.bridge else None
        try:
            self.camera_preview.frame = (
                crop_frame(frame, self.flight.roi) if frame and self.flight.roi else None
            )
        except ValueError:
            self.camera_preview.frame = None
        self.camera_preview.update()
        self.preview.update()
        self.refresh_buttons()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ApplicationDeactivate:
            # A background AI mission continues; only physical mouse holds lose ownership.
            self.flight.release_axis()
            if self.holding or self.demo_started is not None:
                self.holding = False
                self.demo_started = None
                if self.bridge:
                    try:
                        self.bridge.release_all()
                    except Exception as exc:
                        self.i18n.set(self.status, "setText", error_text(exc))
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.release()
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.release()
        self.closing = True
        if self.busy:
            self.i18n.set(self.status, "setText", m("작업 정리 후 종료합니다…"))
            event.ignore()
            return
        self.timer.stop()
        self.simulation_panel.shutdown()
        QApplication.instance().removeEventFilter(self)
        if self.bridge:
            self.bridge.close()
        if self.lab:
            self.lab.close()
        event.accept()


def configure_application(app):
    app.setApplicationName("Zipcontrol")
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget { background: #142030; color: #e5edf9; font-size: 13px; }
        QPushButton { background: #263a52; padding: 10px; border-radius: 6px; }
        QPushButton:hover { background: #365373; }
        QPushButton:disabled { background: #1d2b3d; color: #64738b; }
        QGroupBox { border: 1px solid #35465d; border-radius: 6px; margin-top: 15px; padding: 12px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #95b6dd; }
        QDoubleSpinBox { padding: 5px; background: #0c1625; }
    """)


def run(serial=None, server_path=None):
    app = QApplication(sys.argv)
    configure_application(app)
    window = Window(serial, server_path)
    signal.signal(signal.SIGINT, lambda *_: window.close())
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    window.show()
    return app.exec()
