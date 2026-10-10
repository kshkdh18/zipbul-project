"""Qt presentation of the pure command simulator."""

import struct
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .i18n import message as m
from .localized_ui import I18n
from .simulation import Simulation


class SceneState(QObject):
    changed = Signal()

    def __init__(self, simulation, i18n):
        super().__init__()
        self.simulation = simulation
        self.i18n = i18n
        i18n.changed.connect(self.changed.emit)

    legend = Property(
        str,
        lambda self: self.i18n.render(m("초록 전후  ·  파랑 좌우  ·  노랑 상하  ·  보라 회전")),
        notify=changed,
    )

    position = Property(
        QVector3D,
        lambda self: QVector3D(self.simulation.x * 100, self.simulation.y * 100, self.simulation.z * 100),
        notify=changed,
    )
    heading = Property(float, lambda self: -self.simulation.yaw, notify=changed)
    forward = Property(float, lambda self: self.simulation.axes["forward"], notify=changed)
    lateral = Property(float, lambda self: self.simulation.axes["lateral"], notify=changed)
    vertical = Property(float, lambda self: self.simulation.axes["vertical"], notify=changed)
    turn = Property(float, lambda self: self.simulation.axes["yaw"], notify=changed)
    arrows = Property(bool, lambda self: self.simulation.show_arrows, notify=changed)
    moving = Property(bool, lambda self: self.simulation.deadline > 0, notify=changed)


class TrailGeometry(QQuick3DGeometry):
    def set_points(self, points):
        self.clear()
        self.setStride(12)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.LineStrip)
        self.addAttribute(
            QQuick3DGeometry.Attribute.Semantic.PositionSemantic,
            0,
            QQuick3DGeometry.Attribute.ComponentType.F32Type,
        )
        vertices = [tuple(v * 100 for v in p) for p in points]
        self.setVertexData(b"".join(struct.pack("fff", *p) for p in vertices))
        self.setBounds(
            QVector3D(*(min(p[i] for p in vertices) for i in range(3))),
            QVector3D(*(max(p[i] for p in vertices) for i in range(3))),
        )
        self.update()


class SimulationPanel(QWidget):
    def __init__(self, stream, i18n=None):
        super().__init__()
        self.i18n = i18n or I18n(parent=self)
        self.stream = stream
        self.simulation = Simulation()
        self.scene_state = SceneState(self.simulation, self.i18n)
        self.trail_geometry = TrailGeometry()
        self._trail_snapshot = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        title = self.i18n.widget(QLabel, m("이동 가이드  /  3D"))
        title.setStyleSheet("color: #60e5c3; font-weight: 700; font-size: 16px")
        top.addWidget(title)
        top.addStretch()
        reset = self.i18n.widget(QPushButton, m("궤적 초기화"))
        reset.clicked.connect(self.reset)
        top.addWidget(reset)
        layout.addLayout(top)
        self.view = QQuickWidget()
        self.scene_state.setParent(self.view)
        self.view.setMinimumSize(400, 320)
        self.view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.view.rootContext().setContextProperty("guideState", self.scene_state)
        self.view.rootContext().setContextProperty("trailGeometry", self.trail_geometry)
        self.view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/DroneScene.qml")))
        layout.addWidget(self.view, 1)
        self.label = self.i18n.widget(QLabel, m("이동 지시 대기"))
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size: 25px; font-weight: 700; padding: 8px; color: #f0fbff")
        layout.addWidget(self.label)
        self.reason = self.i18n.widget(QLabel, m("목표를 입력하고 카메라 영역을 지정하세요."))
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("font-size: 15px; padding: 8px; color: #b6ccdc")
        layout.addWidget(self.reason)
        self.status = self.i18n.widget(QLabel, m("명령 기반 가상 궤적 · 실제 위치 측정값이 아닙니다"))
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #7f9aaf; padding: 8px")
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.tick()

    def shutdown(self):
        # Destroy QML bindings while their Python context objects still exist.
        self.timer.stop()
        self.view.setSource(QUrl())

    def reset(self):
        self.simulation.advance(time.monotonic())
        self.simulation.reset()
        self.tick()

    def tick(self):
        for event in self.stream.drain():
            self.simulation.consume(event)
        self.simulation.advance(time.monotonic())
        self.scene_state.changed.emit()
        points = tuple(self.simulation.trail)
        if points != self._trail_snapshot:
            self.trail_geometry.set_points(points)
            self._trail_snapshot = points
        labels = self.simulation.label.split(" · ")
        instruction = m(
            " · ".join("{p" + str(i) + "}" for i in range(len(labels))),
            **{f"p{i}": m(value) for i, value in enumerate(labels)},
        )
        self.i18n.set(self.label, "setText", instruction)
        self.i18n.set(self.reason, "setText", self.simulation.reason)
        self.i18n.set(
            self.status,
            "setText",
            m(
                "{p0} · 명령 기반 가상 궤적\n실제 위치 측정값이 아닙니다 · 드래그로 시점 회전 / 휠로 확대",
                p0=m(self.simulation.state),
            ),
        )
        if self.view.status() == QQuickWidget.Status.Error:
            self.i18n.set(
                self.status,
                "setText",
                m("3D 화면 오류: ") + "; ".join((e.toString() for e in self.view.errors())),
            )
