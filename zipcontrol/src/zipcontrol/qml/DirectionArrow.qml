import QtQuick
import QtQuick3D

Node {
    property color tint: "#6df1cc"
    Model {
        source: "#Cylinder"
        y: 48
        scale: Qt.vector3d(0.065, 0.8, 0.065)
        materials: PrincipledMaterial { baseColor: tint; metalness: 0.2; roughness: 0.45 }
    }
    Model {
        source: "#Cone"
        y: 99
        scale: Qt.vector3d(0.23, 0.3, 0.23)
        materials: PrincipledMaterial { baseColor: tint; metalness: 0.2; roughness: 0.45 }
    }
}
