import QtQuick
import QtQuick3D

Rectangle {
    id: root
    color: "#0c1726"
    property real azimuth: 28
    property real elevation: -30
    property real zoom: 620
    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#0c1726"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        Node {
            position: guideState.position
            eulerRotation: Qt.vector3d(root.elevation, root.azimuth, 0)
            PerspectiveCamera { z: root.zoom; clipNear: 1; clipFar: 100000 }
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-35, -25, 0); brightness: 1.3 }
        DirectionalLight { eulerRotation: Qt.vector3d(-15, 145, 0); brightness: 0.6 }
        Node {
            // A local grid follows horizontal travel, while height remains visible.
            x: Math.floor(guideState.position.x / 100) * 100
            z: Math.floor(guideState.position.z / 100) * 100
            y: -65
            Repeater3D {
                model: 31
                delegate: Node {
                    required property int index
                    Model {
                        source: "#Cube"
                        x: (index - 15) * 100
                        scale: Qt.vector3d(0.008, 0.008, 30)
                        materials: DefaultMaterial { diffuseColor: "#294456"; lighting: DefaultMaterial.NoLighting }
                    }
                    Model {
                        source: "#Cube"
                        z: (index - 15) * 100
                        scale: Qt.vector3d(30, 0.008, 0.008)
                        materials: DefaultMaterial { diffuseColor: "#294456"; lighting: DefaultMaterial.NoLighting }
                    }
                }
            }
        }
        Model {
            geometry: trailGeometry
            materials: DefaultMaterial { diffuseColor: "#59dabb"; lighting: DefaultMaterial.NoLighting }
        }
        Node {
            position: guideState.position
            eulerRotation.y: guideState.heading
            Node {
                eulerRotation.x: guideState.moving ? -guideState.forward * 12 : 0
                eulerRotation.z: guideState.moving ? -guideState.lateral * 12 : 0
                Model {
                    source: "#Cube"
                    scale: Qt.vector3d(0.55, 0.17, 0.75)
                    materials: PrincipledMaterial { baseColor: "#dceaf2"; metalness: 0.6; roughness: 0.35 }
                }
                Model {
                    source: "#Sphere"; z: -40
                    scale: Qt.vector3d(0.19, 0.13, 0.14)
                    materials: PrincipledMaterial { baseColor: "#51efc5"; emissiveFactor: Qt.vector3d(0.1, 0.5, 0.35) }
                }
                Repeater3D {
                    model: 4
                    delegate: Node {
                        required property int index
                        x: index % 2 === 0 ? -46 : 46
                        z: index < 2 ? -42 : 42
                        Model {
                            source: "#Cube"
                            x: parent.x > 0 ? -18 : 18
                            scale: Qt.vector3d(0.6, 0.06, 0.08)
                            materials: PrincipledMaterial { baseColor: "#6d859e"; metalness: 0.5 }
                        }
                        Model {
                            source: "#Cylinder"
                            scale: Qt.vector3d(0.43, 0.055, 0.43)
                            materials: PrincipledMaterial { baseColor: "#425c76"; roughness: 0.7 }
                        }
                        Model {
                            source: "#Cube"; y: 5
                            scale: Qt.vector3d(0.5, 0.022, 0.065)
                            eulerRotation.y: index * 53
                            materials: PrincipledMaterial { baseColor: "#91aac0" }
                        }
                    }
                }
            }
            DirectionArrow {
                visible: guideState.arrows && Math.abs(guideState.forward) > 0.001
                z: guideState.forward > 0 ? -62 : 62
                eulerRotation.x: guideState.forward > 0 ? -90 : 90
                tint: "#5ee7c3"
            }
            DirectionArrow {
                visible: guideState.arrows && Math.abs(guideState.lateral) > 0.001
                x: guideState.lateral > 0 ? 72 : -72
                eulerRotation.z: guideState.lateral > 0 ? -90 : 90
                tint: "#68b6ff"
            }
            DirectionArrow {
                visible: guideState.arrows && Math.abs(guideState.vertical) > 0.001
                y: guideState.vertical > 0 ? 20 : -20
                eulerRotation.z: guideState.vertical > 0 ? 0 : 180
                tint: "#ffd078"
            }
            Node {
                visible: guideState.arrows && Math.abs(guideState.turn) > 0.001
                y: 65
                Repeater3D {
                    model: 25
                    delegate: Model {
                        required property int index
                        property real theta: (index * 5 - 60) * Math.PI / 180
                        source: "#Sphere"
                        x: Math.sin(theta) * 95
                        z: -Math.cos(theta) * 95
                        scale: Qt.vector3d(0.065, 0.065, 0.065)
                        materials: PrincipledMaterial { baseColor: "#e9a5ff" }
                    }
                }
                Model {
                    source: "#Cone"
                    x: guideState.turn > 0 ? 86 : -86
                    z: -48
                    eulerRotation: Qt.vector3d(90, guideState.turn > 0 ? 30 : -30, 0)
                    scale: Qt.vector3d(0.2, 0.3, 0.2)
                    materials: PrincipledMaterial { baseColor: "#e9a5ff" }
                }
            }
        }
    }
    Text {
        anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 18
        text: "ZIPCONTROL  /  COMMAND VIEW"
        color: "#7798ae"; font.pixelSize: 11; font.letterSpacing: 2
    }
    Text {
        anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.margins: 18
        text: guideState.legend
        color: "#90aabb"; font.pixelSize: 12
    }
    MouseArea {
        anchors.fill: parent
        property real lastX: 0
        property real lastY: 0
        onPressed: mouse => { lastX = mouse.x; lastY = mouse.y }
        onPositionChanged: mouse => {
            if (pressed) {
                root.azimuth -= (mouse.x - lastX) * 0.4
                root.elevation = Math.max(-80, Math.min(-5, root.elevation - (mouse.y - lastY) * 0.3))
                lastX = mouse.x; lastY = mouse.y
            }
        }
        onWheel: wheel => { root.zoom = Math.max(250, Math.min(2200, root.zoom - wheel.angleDelta.y * 0.5)) }
        onDoubleClicked: { root.azimuth = 28; root.elevation = -30; root.zoom = 620 }
    }
}
