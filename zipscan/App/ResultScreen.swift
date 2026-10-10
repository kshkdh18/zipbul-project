import SwiftUI
import AVKit
import SceneKit
import ZipscanCore

struct ResultScreen: View {
    let session: StoredSession
    let exports: URL
    var close: (() -> Void)? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var tab = 0
    @State private var exporting = false
    @State private var exportError: String?
    @State private var zipURL: URL?
    @State private var showingShare = false
    @State private var player: AVPlayer?
    @State private var didAutoExport = false
    var body: some View {
        VStack(spacing: 14) {
            HStack(spacing: 14) {
                Button { player?.pause(); if let close { close() } else { dismiss() } } label: { Label("Scans", systemImage: "chevron.left") }.disabled(exporting)
                VStack(alignment: .leading, spacing: 3) {
                    Text(sessionDateLabel(session.manifest.startedAt)).font(.headline)
                    HStack { Text(session.manifest.status.title).foregroundStyle(Theme.status(session.manifest.status)).accessibilityIdentifier("session-status-\(session.manifest.status.rawValue)"); Text("· \(timeLabel(session.manifest.summary.duration))") }.font(.caption)
                }
                Spacer()
                Picker("Scan results", selection: $tab) { Text("3D model").tag(0); Text("Video").tag(1); Text("Quality").tag(2) }.pickerStyle(.segmented).frame(width: 265)
                Button { if zipURL != nil { showingShare = true } else { Task { await export(showShare: true) } } } label: {
                    HStack { if exporting { ProgressView() }; Image(systemName: "square.and.arrow.up"); Text(exporting ? "Creating ZIP" : "Export ZIP") }
                }.buttonStyle(.borderedProminent).disabled(exporting).accessibilityIdentifier("export-zip")
            }
            Group {
                if tab == 0 { MeshPreview(url: session.directory.appendingPathComponent("mesh.obj")) }
                else if tab == 1 {
                    if session.manifest.summary.videoWritten > 0, let player { VideoPlayer(player: player).accessibilityIdentifier("recorded-video").clipShape(RoundedRectangle(cornerRadius: 16)) }
                    else { unavailable("No video available", detail: "Check Quality for storage errors and missing data.") }
                } else { quality }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            if let exportError { Text(DiagnosticText.english(exportError)).font(.caption).foregroundStyle(.yellow).accessibilityIdentifier("export-error") }
            if zipURL != nil { Text("Export ready. Find the ZIP in Files or Finder.").font(.caption).foregroundStyle(Theme.cyan).accessibilityIdentifier("export-complete") }
        }.padding(20).background(Theme.background.ignoresSafeArea()).preferredColorScheme(.dark).tint(Theme.accent)
        .sheet(isPresented: $showingShare) { if let zipURL { ShareSheet(url: zipURL) } }
        .onChange(of: tab) { _, tab in if tab != 1 { player?.pause() } }
        .onDisappear { player?.pause() }
        .task {
            player = AVPlayer(url: session.directory.appendingPathComponent("video.mp4"))
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--auto-export") && !didAutoExport { didAutoExport = true; await export(showShare: false) }
            #endif
        }
    }
    private var quality: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 12) {
                    metric("Video", "\(session.manifest.summary.videoWritten.formatted(.number.locale(appLocale))) frames", "Missing: \(session.manifest.summary.videoDropped.formatted(.number.locale(appLocale)))")
                    metric("Depth", "\(session.manifest.summary.depthWritten.formatted(.number.locale(appLocale))) samples", "Missing: \(session.manifest.summary.depthMissing.formatted(.number.locale(appLocale)))")
                    metric("Mesh", "\(session.manifest.summary.meshFaces.formatted(.number.locale(appLocale))) faces", "Geometry without textures")
                }
                Text("\(session.manifest.settings.imageWidth) × \(session.manifest.settings.imageHeight) · Video \(session.manifest.settings.videoFps) fps · Depth \(session.manifest.settings.depthHz) Hz").font(.caption).foregroundStyle(.secondary)
                Text("This scan records the space. It does not determine whether the site is safe.").font(.subheadline)
                ForEach(Array((session.manifest.warnings + session.manifest.errors + session.manifest.missingFiles.map { "Missing required file: \($0)" }).enumerated()), id: \.offset) { _, message in
                    Label(DiagnosticText.english(message), systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.yellow).textSelection(.enabled)
                }
                if session.manifest.status == .complete { Label("Required data and video–depth alignment passed validation.", systemImage: "checkmark.seal").foregroundStyle(Theme.cyan) }
            }.padding(20)
        }.background(Theme.panel, in: RoundedRectangle(cornerRadius: 16))
    }
    private func metric(_ title: String, _ value: String, _ note: String) -> some View {
        VStack(alignment: .leading, spacing: 7) { Text(title).font(.caption).foregroundStyle(.secondary); Text(value).font(.title3.bold()).monospacedDigit(); Text(note).font(.caption).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading)
    }
    @MainActor private func export(showShare: Bool) async {
        guard !exporting else { return }; exporting = true; exportError = nil
        let previousIdleTimer = UIApplication.shared.isIdleTimerDisabled
        UIApplication.shared.isIdleTimerDisabled = true
        defer {
            exporting = false
            UIApplication.shared.isIdleTimerDisabled = previousIdleTimer
        }
        let source = session.directory, destination = exports
        do {
            zipURL = try await Task.detached(priority: .userInitiated) { try Exporter.export(session: source, destination: destination) }.value
            showingShare = showShare
        } catch { exportError = error.localizedDescription }
    }
}

func unavailable(_ title: String, detail: String) -> some View {
    VStack(spacing: 12) { Image(systemName: "cube.transparent").font(.largeTitle).foregroundStyle(Theme.cyan); Text(title).font(.headline); Text(DiagnosticText.english(detail)).font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center) }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.panel, in: RoundedRectangle(cornerRadius: 16))
}

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: [url], applicationActivities: nil) }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

struct MeshPreview: View {
    let url: URL
    @State private var model: MeshScene?
    @State private var error: String?
    @State private var reset = 0
    var body: some View {
        ZStack(alignment: .bottomLeading) {
            if let model {
                OrbitView(model: model, reset: reset).clipShape(RoundedRectangle(cornerRadius: 16))
                HStack { Text("Drag to rotate · Pinch to zoom").font(.caption).foregroundStyle(.secondary); Spacer(); Button { reset += 1 } label: { Label("Reset view", systemImage: "arrow.counterclockwise") }.buttonStyle(.bordered) }.padding(14)
            } else if let error { unavailable("Could not display the mesh", detail: error) }
            else { ProgressView("Loading the 3D model").frame(maxWidth: .infinity, maxHeight: .infinity) }
        }.task {
            do { model = try await Task.detached(priority: .userInitiated) { try MeshScene.load(url) }.value }
            catch { self.error = error.localizedDescription }
        }
    }
}

struct MeshScene: @unchecked Sendable {
    let scene: SCNScene
    let camera: SCNNode
    let cameraTransform: SCNMatrix4
    let center: SCNVector3
    static func load(_ url: URL) throws -> MeshScene {
        let mesh = try OBJ.read(url)
        var normals = Array(repeating: SIMD3<Float>.zero, count: mesh.vertices.count)
        for i in stride(from: 0, to: mesh.indices.count, by: 3) {
            let a = Int(mesh.indices[i]), b = Int(mesh.indices[i+1]), c = Int(mesh.indices[i+2])
            let n = simd_cross(mesh.vertices[b] - mesh.vertices[a], mesh.vertices[c] - mesh.vertices[a])
            normals[a] += n; normals[b] += n; normals[c] += n
        }
        let vertices = mesh.vertices.map { SCNVector3($0.x, $0.y, $0.z) }
        let normalSource = SCNGeometrySource(normals: normals.map { n in let n = simd_length(n) > 0 ? simd_normalize(n) : SIMD3<Float>(0, 1, 0); return SCNVector3(n.x, n.y, n.z) })
        let data = mesh.indices.withUnsafeBufferPointer { Data(buffer: $0) }
        let element = SCNGeometryElement(data: data, primitiveType: .triangles, primitiveCount: mesh.indices.count / 3, bytesPerIndex: 4)
        let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: vertices), normalSource], elements: [element])
        let material = SCNMaterial(); material.diffuse.contents = UIColor(red: 0.46, green: 0.76, blue: 0.8, alpha: 1)
        material.isDoubleSided = true; material.roughness.contents = 0.85
        geometry.materials = [material]
        let scene = SCNScene(); scene.rootNode.addChildNode(SCNNode(geometry: geometry))
        var low = mesh.vertices[0], high = low
        for v in mesh.vertices { low = simd_min(low, v); high = simd_max(high, v) }
        let center = (low + high) / 2, radius = max(0.5, simd_length(high - low) / 2)
        let camera = SCNNode(); camera.camera = SCNCamera(); camera.camera?.zNear = 0.01; camera.camera?.zFar = Double(max(100, radius * 20))
        camera.simdPosition = center + SIMD3(radius * 1.5, radius, radius * 1.7)
        let target = SCNVector3(center.x, center.y, center.z); camera.look(at: target)
        scene.rootNode.addChildNode(camera)
        return MeshScene(scene: scene, camera: camera, cameraTransform: camera.transform, center: target)
    }
}

struct OrbitView: UIViewRepresentable {
    let model: MeshScene
    let reset: Int
    final class Coordinator { var lastReset = -1 }
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = model.scene; view.pointOfView = model.camera; view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = UIColor(red: 0.065, green: 0.085, blue: 0.115, alpha: 1)
        view.defaultCameraController.interactionMode = .orbitTurntable
        view.defaultCameraController.target = model.center
        return view
    }
    func updateUIView(_ view: SCNView, context: Context) {
        if context.coordinator.lastReset != reset {
            view.defaultCameraController.stopInertia()
            view.pointOfView = model.camera; model.camera.transform = model.cameraTransform
            view.defaultCameraController.target = model.center
            context.coordinator.lastReset = reset
        }
    }
}
