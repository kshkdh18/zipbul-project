"""Mission controls; Qt never runs model inference or a touch loop."""

import json
import math
import time
import uuid
from dataclasses import asdict

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .camera import CameraStore, camera_rect
from .flight_profile import AXES, DEFAULT_AXES, FlightProfile, FlightProfileStore, anchor
from .guard import GuardBridge
from .guidance import GuidanceMission as Mission
from .i18n import error_text
from .i18n import message as m
from .localized_ui import I18n
from .luna import LunaDecider
from .manual import ManualHold
from .planning import AstraPlanner

LABELS = {
    "yaw": m("회전 (+우회전)"),
    "vertical": m("고도 (+상승)"),
    "lateral": m("좌우 (+오른쪽)"),
    "forward": m("전후 (+전진)"),
}

DIRECTIONS = {
    "yaw": (m("좌회전"), m("우회전")),
    "vertical": (m("하강"), m("상승")),
    "lateral": (m("왼쪽 이동"), m("오른쪽 이동")),
    "forward": (m("후진"), m("전진")),
}


def axis_hint(axis, sign, profile):
    name, direction = (profile.axes if profile else DEFAULT_AXES)[axis]
    return (m("저장한 축 설정: ") if profile else m("기본 축 설정: ")) + DIRECTIONS[name][
        sign * direction > 0
    ]


class FlightPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.i18n = getattr(window, "i18n", None) or I18n(parent=self)
        self.store = FlightProfileStore()
        self.camera_store = CameraStore()
        self.roi_epoch = None
        self.profile = None
        self.mission = None
        self.roi = None
        self.roi_points = None
        self.axis_testing = False
        self.axis_hold = None
        self.axis_button = None
        self.last_error = ""
        box = QVBoxLayout(self)
        self.note = self.i18n.widget(
            QLabel, m("Astra 계획 · Luna Decisions 조작\nAI 드래그 100% · 판단당 최대 2초")
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.goal = QTextEdit()
        self.i18n.set(
            self.goal, "setPlaceholderText", m("목표 예: 빨간 의자가 화면 중앙에 오도록 구도를 맞춰")
        )
        self.goal.setFixedHeight(100)
        box.addWidget(self.goal)
        self.controller_mode = QComboBox()
        self.i18n.item(self.controller_mode, m("Astra 계획 + Luna 조작"), "hierarchical")
        self.i18n.item(self.controller_mode, m("Luna 직접 실행"), "direct")
        box.addWidget(self.controller_mode)
        self.subgoal_status = self.i18n.widget(QLabel, m("현재 하위 목표 · 임무 시작 후 표시됩니다."))
        self.subgoal_status.setWordWrap(True)
        self.subgoal_status.setFixedWidth(355)
        box.addWidget(self.subgoal_status)
        self.observe_only = self.i18n.widget(QCheckBox, m("AI 관찰 전용 — AI 명령은 실행하지 않음"))
        self.observe_only.setChecked(False)
        box.addWidget(self.observe_only)
        self.roi_button = self.i18n.widget(QPushButton, m("카메라 영역 지정 · 두 모서리 클릭"))
        self.roi_button.clicked.connect(self.select_roi)
        box.addWidget(self.roi_button)
        self.profile_button = self.i18n.widget(QPushButton, m("축 방향 설정 (선택)"))
        self.profile_button.clicked.connect(self.edit_profile)
        box.addWidget(self.profile_button)
        self.settings_status = self.i18n.widget(
            QLabel, m("기본 축 사용 · 프로필 없이 시작 가능\n왼손: 회전·고도 / 오른손: 좌우·전후")
        )
        self.settings_status.setWordWrap(True)
        box.addWidget(self.settings_status)
        manual_note = self.i18n.widget(
            QLabel,
            m(
                "수동 조작 · 누르는 동안 선택한 스틱 하나만 입력\n놓기 / Esc / 앱 전환 시 해제 · 화살표는 화면 속 스틱 방향"
            ),
        )
        manual_note.setWordWrap(True)
        box.addWidget(manual_note)
        limits = QFormLayout()
        self.manual_strength = QDoubleSpinBox()
        self.manual_strength.setRange(5, 100)
        self.manual_strength.setSingleStep(5)
        self.manual_strength.setDecimals(0)
        self.manual_strength.setValue(100)
        self.i18n.set(self.manual_strength, "setSuffix", " %")
        self.i18n.set(
            self.manual_strength,
            "setToolTip",
            m("수동과 AI에 함께 적용합니다. Luna는 방향을 선택하고 명령은 최대 2초입니다."),
        )
        self.i18n.row(limits, m("드래그 크기 (수동·AI)"), self.manual_strength)
        self.manual_seconds = QDoubleSpinBox()
        self.manual_seconds.setRange(1, 10)
        self.manual_seconds.setSingleStep(0.5)
        self.manual_seconds.setValue(3)
        self.i18n.set(self.manual_seconds, "setSuffix", m(" 초"))
        self.i18n.row(limits, m("한 번 누를 때 최대"), self.manual_seconds)
        box.addLayout(limits)
        self.drag_info = self.i18n.widget(QLabel, m("L/R 보정 후 요청 이동 거리를 표시합니다."))
        self.drag_info.setWordWrap(True)
        self.drag_info.setFixedWidth(355)
        box.addWidget(self.drag_info)
        grid = QGridLayout()
        self.test_buttons = []
        for i, label in enumerate(("L X", "L Y", "R X", "R Y")):
            for j, direction in enumerate((-1, 1)):
                hand = m("왼손") if i < 2 else m("오른손")
                arrow = ("←" if direction < 0 else "→") if i % 2 == 0 else ("↑" if direction < 0 else "↓")
                b = self.i18n.widget(QPushButton, hand + " " + arrow)
                b.setAutoRepeat(False)
                self.i18n.set(
                    b,
                    "setToolTip",
                    m(
                        "{p0} {p1} · 화면 속 스틱을 해당 방향으로 유지합니다.",
                        p0=label,
                        p1="−" if direction < 0 else "+",
                    ),
                )
                b.pressed.connect(lambda axis=i, sign=direction: self.test_axis(axis, sign))
                b.released.connect(self.release_axis)
                grid.addWidget(b, i // 2, (i % 2) * 2 + j)
                self.test_buttons.append(b)
        box.addLayout(grid)
        self.start_button = self.i18n.widget(QPushButton, m("AI 임무 시작"))
        self.start_button.clicked.connect(self.start)
        box.addWidget(self.start_button)
        self.pause_button = self.i18n.widget(QPushButton, m("일시 중단 / 입력 해제  [Esc]"))
        self.pause_button.clicked.connect(lambda: self.stop("user_paused"))
        box.addWidget(self.pause_button)
        self.end_button = self.i18n.widget(QPushButton, m("임무 종료 / 수동 인계"))
        self.end_button.clicked.connect(lambda: self.stop("user_ended"))
        box.addWidget(self.end_button)
        self.status = self.i18n.widget(QLabel, m("카메라 영역과 목표를 지정하면 이동 안내를 시작합니다."))
        self.status.setWordWrap(True)
        self.status.setFixedWidth(355)
        box.addWidget(self.status)
        box.addStretch()

    @property
    def active(self):
        return bool(self.mission and self.mission.executor.running) or self.axis_testing

    @property
    def busy(self):
        return bool(self.mission and self.mission.busy) or self.axis_testing

    def connected(self):
        self.profile = None
        self.roi = None
        b = self.window.bridge
        f = b.latest_frame()
        if not f:
            return
        try:
            self.profile = self.store.load(b.adb.serial, f.width, f.height)
            if self.profile:
                self.i18n.set(self.status, "setText", m("저장한 축 설정을 불러왔습니다."))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.i18n.set(
                self.status, "setText", m("저장 설정을 읽지 못해 기본 축을 사용합니다: ") + error_text(exc)
            )
        try:
            self.roi = self.camera_store.load(b.adb.serial, f.width, f.height)
            self.roi_epoch = f.epoch
            self.window.preview.camera_rect = QRectF(*self.roi) if self.roi else None
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.i18n.set(self.status, "setText", m("카메라 영역을 다시 지정하세요: ") + error_text(exc))

    def select_roi(self):
        frame = self.window.bridge.latest_frame() if self.window.bridge else None
        if frame is None:
            self.i18n.set(self.status, "setText", m("Android의 최신 화면이 필요합니다."))
            return
        self.roi_epoch = frame.epoch
        self.roi = None
        self.window.preview.camera_rect = None
        self.window.calibrating = False
        self.window.preview.points = []
        self.release_axis()
        if self.mission and self.mission.executor.running:
            self.mission.set_camera_roi(None)
        self.roi_points = []
        self.i18n.set(self.status, "setText", m("카메라 영상의 왼쪽 위 → 오른쪽 아래를 클릭하세요."))

    def point(self, x, y):
        if self.roi_points is None:
            return False
        frame = self.window.bridge.latest_frame()
        if frame is None or frame.epoch != self.roi_epoch:
            self.roi_points = None
            self.i18n.set(self.status, "setText", m("화면이 변경되었습니다. 카메라 영역을 다시 지정하세요."))
            return True
        self.roi_points.append((x, y))
        self.window.preview.points = list(self.roi_points)
        if len(self.roi_points) == 2:
            (xa, ya), (xb, yb) = self.roi_points
            try:
                roi = list(
                    camera_rect(
                        [min(xa, xb), min(ya, yb), abs(xb - xa), abs(yb - ya)], frame.width, frame.height
                    )
                )
                self.roi = roi
                self.window.preview.camera_rect = QRectF(*roi)
                if self.mission and self.mission.executor.running:
                    self.mission.set_camera_roi(roi)
                self.camera_store.save(self.window.bridge.adb.serial, frame.width, frame.height, roi)
                self.i18n.set(
                    self.status, "setText", m("카메라 영역만 AI에 전달합니다. 영상 미리보기를 확인하세요.")
                )
            except (ValueError, OSError) as exc:
                self.i18n.set(self.status, "setText", error_text(exc))
            self.roi_points = None
            self.window.preview.points = []
        return True

    def edit_profile(self):
        b = self.window.bridge
        if not b or not b.controller.sticks:
            self.i18n.set(self.status, "setText", m("L/R 조이스틱 위치 보정이 필요합니다."))
            return
        dialog = QDialog(self)
        self.i18n.set(dialog, "setWindowTitle", m("축 방향 설정 (선택)"))
        layout = QFormLayout(dialog)
        combos = []
        current = self.profile.axes if self.profile else DEFAULT_AXES
        for i, name in enumerate(("L X", "L Y", "R X", "R Y")):
            combo = QComboBox()
            for axis in AXES:
                for sign in (1, -1):
                    self.i18n.item(
                        combo, LABELS[axis] + (m(" · 정방향") if sign == 1 else m(" · 반전")), (axis, sign)
                    )
            # Qt converts tuple item data to QVariant lists; compare the semantic values explicitly.
            axis_name, axis_sign = current[i]
            combo.setCurrentIndex(AXES.index(axis_name) * 2 + (0 if axis_sign == 1 else 1))
            self.i18n.row(layout, name, combo)
            combos.append(combo)
        error = self.i18n.widget(QLabel, "")
        error.setWordWrap(True)
        layout.addRow(error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.rejected.connect(dialog.reject)
        self.i18n.set(buttons.button(QDialogButtonBox.StandardButton.Save), "setText", m("저장"))
        self.i18n.set(buttons.button(QDialogButtonBox.StandardButton.Cancel), "setText", m("취소"))

        def save():
            try:
                f = b.latest_frame()
                if not f or time.monotonic() - f.decoded_at > 0.5:
                    raise ValueError(m("최신 조종 화면이 필요합니다."))
                profile = FlightProfile(
                    b.adb.serial,
                    f.width,
                    f.height,
                    [asdict(s) for s in b.controller.sticks],
                    [list(c.currentData()) for c in combos],
                    self.roi,
                    [anchor(f, s) for s in b.controller.sticks],
                    False,
                )
                self.store.save(profile)
                self.profile = profile
                self.i18n.set(
                    self.status,
                    "setText",
                    m("축 설정 저장 완료. 관찰 전용을 해제하면 실제 입력을 실행합니다."),
                )
                dialog.accept()
            except (ValueError, OSError, TypeError) as exc:
                self.i18n.set(error, "setText", error_text(exc))

        buttons.accepted.connect(save)
        layout.addRow(buttons)
        dialog.exec()

    def test_axis(self, axis, sign):
        if self.busy or self.window.busy:
            return
        b = self.window.bridge
        if not isinstance(b, GuardBridge) or not b.controller.sticks:
            return
        self.last_error = ""
        self.axis_button = self.test_buttons[axis * 2 + (sign > 0)]
        if not self.axis_button.isDown():
            return
        self.axis_testing = True
        hold = ManualHold(
            b,
            axis,
            sign,
            self.manual_seconds.value(),
            strength=self.manual_strength.value() / 100,
            stream=getattr(self.window, "command_stream", None),
            axes=self.profile.axes if self.profile else DEFAULT_AXES,
        )
        self.axis_hold = hold
        self.i18n.set(self.status, "setText", m("축 확인 입력 중 · 버튼을 놓으면 해제합니다."))

        def test():
            log_path = self.window.output / f"manual-{uuid.uuid4().hex[:10]}.json"
            try:
                message = hold.run()
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(
                        json.dumps(
                            {
                                "scope": "manual joystick input; no aircraft-motion measurement",
                                "events": hold.events,
                                "commands": hold.command_count,
                                "updates": hold.update_count,
                                "reason": hold.reason,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n"
                    )
                    return m(
                        "{p0}\n요청 이동 {p1:.1f}px · 갱신 {p2}회\n기록: {p3}",
                        p0=message,
                        p1=hold.distance_px,
                        p2=hold.update_count,
                        p3=log_path,
                    )
                except OSError as exc:
                    return message + m(" · 진단 기록 저장 실패: ") + error_text(exc)
            finally:
                self.axis_testing = False

        def finished(message):
            self.axis_button = None
            self.axis_hold = None
            self.i18n.set(self.status, "setText", message)

        self.window.work(test, finished)

    def release_axis(self):
        if self.axis_hold:
            self.axis_hold.stop()

    def start(self):
        try:
            self.last_error = ""
            if self.busy:
                return
            self.window.release()
            frame = self.window.bridge.latest_frame()
            if frame is None:
                raise ValueError(m("Android의 최신 화면이 필요합니다."))
            camera_rect(self.roi, frame.width, frame.height)
            provider = LunaDecider()
            try:
                planner = AstraPlanner()
            except Exception:
                provider.close()
                raise
            self.mission = Mission(
                self.window.bridge,
                provider,
                planner,
                self.goal.toPlainText(),
                live=not self.observe_only.isChecked(),
                profile=self.profile,
                mode=self.controller_mode.currentData(),
                language=self.i18n.language,
                camera_roi=self.roi,
                drag_strength=self.manual_strength.value() / 100,
                stream=getattr(self.window, "command_stream", None),
            )
            try:
                self.mission.start(require_ui=False)
            except Exception:
                provider.close()
                planner.close()
                raise
        except Exception as exc:
            self.last_error = error_text(exc)
            self.i18n.set(self.status, "setText", error_text(exc))

    def stop(self, why="user_paused"):
        if self.axis_hold:
            self.axis_hold.stop(why)
        if self.mission:
            self.mission.stop(why)
        if getattr(self.window, "command_stream", None):
            self.window.command_stream.release(why)

    def tick(self):
        if self.axis_testing and self.axis_hold:
            if self.axis_button and self.axis_button.isDown():
                self.axis_hold.pressed()
            else:
                self.axis_hold.stop()
        b = self.window.bridge
        points = []
        if self.axis_testing and self.axis_hold:
            hold = self.axis_hold
            points = hold.target_points if not hold.cancelled.is_set() else []
            self.i18n.set(
                self.drag_info,
                "setText",
                m(
                    "요청 이동 {p0:.1f}px · 이동 갱신 {p1}회\nAndroid 보고 접촉 {p2}개 · 노란 점은 요청 위치",
                    p0=hold.distance_px,
                    p1=hold.update_count,
                    p2=hold.last_ack.get("active", "?"),
                ),
            )
        elif b and b.controller.sticks and self.mission and self.mission.executor.running:
            command = self.mission.executor.command
            if command:
                xy = (command["left_xy"], command["right_xy"])
                points = [
                    s.target(v) if v is not None else None
                    for s, v in zip(b.controller.sticks, xy, strict=True)
                ]
                distances = [
                    s.radius * math.hypot(*v) if v is not None else 0
                    for s, v in zip(b.controller.sticks, xy, strict=True)
                ]
                mode = m("AI 요청 이동") if self.mission.executor.live else m("AI 관찰 전용 제안")
                self.i18n.set(
                    self.drag_info,
                    "setText",
                    m(
                        "{p0}: L {p1:.1f}px / R {p2:.1f}px\n노란 점은 요청 위치 · 기체 움직임 측정값이 아닙니다.",
                        p0=mode,
                        p1=distances[0],
                        p2=distances[1],
                    ),
                )
            else:
                self.i18n.set(self.drag_info, "setText", m("AI 판단 대기 · 현재 스틱 입력 해제"))
        elif b and b.controller.sticks:
            strength = self.manual_strength.value() / 100
            left, right = b.controller.sticks
            self.i18n.set(
                self.drag_info,
                "setText",
                m(
                    "요청 이동: L {p0:.1f}px / R {p1:.1f}px\n수신 영상 기준 · 드래그 비율은 기체 속도를 뜻하지 않습니다.",
                    p0=left.radius * strength,
                    p1=right.radius * strength,
                ),
            )
        else:
            self.i18n.set(self.drag_info, "setText", m("L/R 보정 후 요청 이동 거리를 표시합니다."))
        self.window.preview.requested_targets = points
        self.i18n.set(
            self.note,
            "setText",
            m(
                "Astra 계획 · Luna Decisions 조작\nAI 드래그 {p0:g}% · 판단당 최대 2초 · 손으로 이동",
                p0=self.manual_strength.value(),
            ),
        )
        ready = bool(b and not b.error and b.latest_frame() is not None and not self.window.busy)
        calibrated = ready and b.controller.sticks is not None
        busy = self.busy
        self.start_button.setEnabled(
            ready
            and self.roi is not None
            and not busy
            and bool(self.goal.toPlainText().strip())
            and (self.observe_only.isChecked() or calibrated)
        )
        self.i18n.set(
            self.start_button,
            "setText",
            m("AI 관찰 시작") if self.observe_only.isChecked() else m("AI 임무 시작 · 실제 입력"),
        )
        self.goal.setEnabled(not busy)
        self.controller_mode.setEnabled(not busy)
        self.observe_only.setEnabled(not busy)
        self.roi_button.setEnabled(ready and not self.axis_testing)
        self.profile_button.setEnabled(calibrated and not busy)
        self.i18n.set(
            self.settings_status,
            "setText",
            m("저장한 축 설정 사용")
            if self.profile
            else m("기본 축 사용 · 프로필 없이 시작 가능\n왼손: 회전·고도 / 오른손: 좌우·전후"),
        )
        self.manual_seconds.setEnabled(not busy)
        self.manual_strength.setEnabled(not busy)
        for index, button in enumerate(self.test_buttons):
            # Disabling the pressed QPushButton cancels its press. Keep only that button live.
            holding_this = self.axis_testing and button is self.axis_button
            button.setEnabled(holding_this or (calibrated and not busy and isinstance(b, GuardBridge)))
            self.i18n.set(
                button, "setToolTip", axis_hint(index // 2, -1 if index % 2 == 0 else 1, self.profile)
            )
        if self.mission and not self.axis_testing:
            self.mission.executor.ui_heartbeat = time.monotonic()
            message = self.mission.message or self.mission.executor.reason
            if message.startswith("need_operator: "):
                message = m("AI 인계 요청 (화면 판단): ") + message.removeprefix("need_operator: ")
            subgoal = self.mission.subgoal
            self.i18n.set(
                self.subgoal_status,
                "setText",
                m("현재 목표: {p0}\n완료 조건: {p1}", p0=subgoal.goal, p1=subgoal.completion_criteria)
                if subgoal
                else m("Astra가 현재 하위 목표를 계획합니다."),
            )
            astra_count = sum(r["stage"] == "astra" for r in self.mission.records)
            luna_count = sum(r["stage"] == "luna" for r in self.mission.records)
            mode = "Astra + Luna" if self.mission.mode == "hierarchical" else m("Luna 직접")
            self.i18n.set(
                self.status,
                "setText",
                m(
                    "{p0} · {p1} · {p2}\n계획 {p3}회 · Luna {p4}회 · 만료 {p5}회\n기록: {p6}",
                    p0=mode,
                    p1=self.mission.state_label,
                    p2=message,
                    p3=astra_count,
                    p4=luna_count,
                    p5=self.mission.executor.expirations,
                    p6=self.mission.journal.path,
                ),
            )
        if self.last_error:
            self.i18n.set(self.status, "setText", self.last_error)
