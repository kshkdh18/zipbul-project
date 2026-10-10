import SwiftUI
import AVFoundation
import ARKit
import ZipscanCore

@main struct ZipscanApp: App {
    var body: some Scene {
        WindowGroup { LibraryScreen().environment(\.locale, appLocale).preferredColorScheme(.dark).tint(Theme.accent) }
    }
}

enum Theme {
    static let background = Color(red: 0.045, green: 0.065, blue: 0.09)
    static let panel = Color(red: 0.09, green: 0.12, blue: 0.16)
    static let accent = Color(red: 0.98, green: 0.48, blue: 0.24)
    static let cyan = Color(red: 0.37, green: 0.82, blue: 0.9)
    static func status(_ status: SessionStatus) -> Color {
        switch status { case .complete: return cyan; case .partial: return .yellow; case .failed: return .red; default: return .secondary }
    }
}

let appLocale = Locale(identifier: "en_US")

func sessionDateLabel(_ date: Date) -> String { date.formatted(.dateTime.year().month(.abbreviated).day(.twoDigits).hour().minute().locale(appLocale)) }

func timeLabel(_ seconds: Double) -> String { String(format: "%02d:%02d", max(0, Int(seconds)) / 60, max(0, Int(seconds)) % 60) }

struct LibraryScreen: View {
    @StateObject private var library = SessionLibrary()
    @State private var newScan = false
    @State private var selected: StoredSession?
    @State private var deleting: StoredSession?
    var body: some View {
        HStack(spacing: 28) {
            VStack(alignment: .leading, spacing: 18) {
                Label("ZIPSCAN", systemImage: "viewfinder").font(.system(size: 19, weight: .bold, design: .rounded)).foregroundStyle(Theme.accent)
                Text("Capture spaces.\nKeep the context.").font(.system(size: 30, weight: .bold)).fixedSize(horizontal: false, vertical: true)
                Text("Video and 3D, in one scan.\nMove slowly to map the room.").font(.subheadline).foregroundStyle(.secondary)
                Spacer(minLength: 0)
                Button { newScan = true } label: { Label("New scan", systemImage: "plus").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12) }
                    .buttonStyle(.borderedProminent).accessibilityIdentifier("new-scan").disabled(library.loading)
                Text("iPhone LiDAR · Up to 10 minutes").font(.caption).foregroundStyle(.secondary)
            }.frame(width: 265)
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text("Saved scans").font(.title3.bold()); Text("\(library.sessions.count)").foregroundStyle(.secondary); Spacer(); if library.loading { ProgressView() } }
                if library.sessions.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "square.stack.3d.up").font(.system(size: 40)).foregroundStyle(Theme.cyan)
                        Text(library.loading ? "Loading your scans" : "Capture your first space").font(.headline)
                        Text("Your saved 3D scans and videos appear here.").font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.panel, in: RoundedRectangle(cornerRadius: 20))
                } else {
                    ScrollView {
                        LazyVStack(spacing: 10) {
                            ForEach(library.sessions) { session in
                                HStack(spacing: 14) {
                                    Button { selected = session } label: {
                                        HStack(spacing: 14) {
                                            Image(systemName: "cube.transparent").font(.title2).foregroundStyle(Theme.cyan).frame(width: 48, height: 48).background(.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 12))
                                            VStack(alignment: .leading, spacing: 5) {
                                                Text(sessionDateLabel(session.manifest.startedAt)).font(.headline).foregroundStyle(.white)
                                                Text("\(timeLabel(session.manifest.summary.duration)) · \(session.manifest.summary.meshFaces.formatted(.number.locale(appLocale))) mesh faces").font(.caption).foregroundStyle(.secondary)
                                            }
                                            Spacer()
                                            Text(session.manifest.status.title).font(.caption.bold()).foregroundStyle(Theme.status(session.manifest.status))
                                        }.contentShape(Rectangle())
                                    }.buttonStyle(.plain).accessibilityIdentifier("session-\(session.id)")
                                    Button(role: .destructive) { deleting = session } label: { Image(systemName: "trash").padding(10) }.accessibilityLabel("Delete scan").accessibilityIdentifier("delete-session-\(session.id)")
                                }.padding(12).background(Theme.panel, in: RoundedRectangle(cornerRadius: 16))
                            }
                        }
                    }
                }
                if let error = library.error { Text(DiagnosticText.english(error)).font(.caption).foregroundStyle(.yellow).lineLimit(2) }
            }
        }
        .padding(.horizontal, 28).padding(.vertical, 22).background(Theme.background.ignoresSafeArea())
        .task {
            await library.refresh()
            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--smoke-seconds") { newScan = true }
            #endif
        }
        .fullScreenCover(isPresented: $newScan, onDismiss: { Task { await library.refresh() } }) { CaptureFlow(library: library) }
        .fullScreenCover(item: $selected) { session in ResultScreen(session: session, exports: library.exports) }
        .alert("Delete this scan?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
            Button("Cancel", role: .cancel) { deleting = nil }
            Button("Delete", role: .destructive) { if let session = deleting { Task { await library.delete(session) } }; deleting = nil }
        } message: { Text("This deletes the scan, video, and exported ZIP from this device. Copies shared elsewhere will remain.") }
    }
}

struct CaptureFlow: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var library: SessionLibrary
    @State private var controller: CaptureController?
    @State private var completed: StoredSession?
    @State private var error: String?
    @State private var checking = false
    private var supported: Bool { ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) && ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) }
    var body: some View {
        Group {
            if let completed { ResultScreen(session: completed, exports: library.exports, close: { dismiss() }) }
            else if let controller { ScanScreen(controller: controller) }
            else {
                HStack(spacing: 36) {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Ready to scan").font(.largeTitle.bold())
                        Text("Hold your iPhone sideways.\nMove slowly.").font(.title2.weight(.medium))
                        Text("Scan walls, floors, and nearby objects from different angles. Keep the rear camera and LiDAR uncovered.").foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Button("Back") { dismiss() }.buttonStyle(.bordered)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 14) {
                        readiness("LiDAR scanning", detail: supported ? "Supported iPhone" : "A LiDAR-enabled iPhone is required", ok: supported)
                        readiness("Storage", detail: "\(Files.available(library.root).formatted(.byteCount(style: .file).locale(appLocale))) available · 6 GB required", ok: Files.available(library.root) >= 6_000_000_000)
                        readiness("Camera", detail: "Video and depth · No audio", ok: AVCaptureDevice.authorizationStatus(for: .video) != .denied)
                        Text("Scanning stops and saves at 10 minutes. Mesh colors do not indicate safety.").font(.caption).foregroundStyle(.secondary)
                        if let error { Text(DiagnosticText.english(error)).font(.caption).foregroundStyle(.yellow) }
                        Button { Task { await start() } } label: {
                            HStack { if checking { ProgressView() }; Text(checking ? "Checking" : "Start scan").bold() }.frame(maxWidth: .infinity).padding(.vertical, 10)
                        }.buttonStyle(.borderedProminent).disabled(checking || !supported).accessibilityIdentifier("start-scan")
                        if AVCaptureDevice.authorizationStatus(for: .video) == .denied {
                            Button("Camera settings") { if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) } }.font(.caption)
                        }
                    }.padding(22).frame(maxWidth: .infinity).background(Theme.panel, in: RoundedRectangle(cornerRadius: 20))
                }.padding(28).background(Theme.background.ignoresSafeArea())
                .task {
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--smoke-seconds") { await start() }
                    #endif
                }
            }
        }.preferredColorScheme(.dark).tint(Theme.accent)
    }
    private func readiness(_ title: String, detail: String, ok: Bool) -> some View {
        HStack(spacing: 12) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill").foregroundStyle(ok ? Theme.cyan : .yellow)
            VStack(alignment: .leading, spacing: 3) { Text(title).font(.headline); Text(detail).font(.caption).foregroundStyle(.secondary) }
        }
    }
    @MainActor private func start() async {
        guard !checking else { return }; checking = true; defer { checking = false }
        do {
            guard Files.available(library.root) >= 6_000_000_000 else { throw ScanError.invalid("At least 6 GB of free storage is required to start a scan.") }
            let permission = AVCaptureDevice.authorizationStatus(for: .video)
            let granted: Bool
            if permission == .notDetermined { granted = await AVCaptureDevice.requestAccess(for: .video) }
            else { granted = permission == .authorized }
            guard granted else { throw ScanError.invalid("Allow camera access in Settings to start scanning.") }
            let controller = CaptureController()
            controller.onFinish = { manifest in
                completed = StoredSession(directory: library.root.appendingPathComponent(manifest.id), manifest: manifest)
                self.controller = nil
            }
            var settings = CaptureSettings()
            #if DEBUG
            let args = ProcessInfo.processInfo.arguments
            if let i = args.firstIndex(of: "--smoke-seconds"), args.indices.contains(i + 1), let seconds = Double(args[i + 1]) { settings.maxDuration = min(600, max(5, seconds)) }
            if args.contains("--depth-5hz") { settings.depthHz = 5 }
            if args.contains("--video-15fps") { settings.videoFps = 15 }
            #endif
            try controller.start(directoryRoot: library.root, settings: settings)
            self.controller = controller
        } catch { self.error = error.localizedDescription }
    }
}

struct ScanScreen: View {
    @ObservedObject var controller: CaptureController
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        ZStack {
            CameraView(controller: controller).ignoresSafeArea()
            LinearGradient(colors: [.black.opacity(0.65), .clear, .black.opacity(0.6)], startPoint: .top, endPoint: .bottom).ignoresSafeArea().allowsHitTesting(false)
            VStack {
                HStack {
                    HStack(spacing: 9) { Circle().fill(controller.phase == .scanning ? .red : .yellow).frame(width: 9, height: 9); Text(controller.phase == .preparing ? "Starting sensors" : "Scanning").bold(); Text(timeLabel(controller.elapsed)).monospacedDigit() }
                        .padding(12).background(.black.opacity(0.6), in: Capsule())
                    Spacer()
                    Label(controller.tracking, systemImage: "location.viewfinder").font(.subheadline).padding(12).background(.black.opacity(0.6), in: Capsule())
                }
                Spacer()
                if let warning = controller.thermalWarning { Text(warning).foregroundStyle(.yellow).padding(8).background(.black.opacity(0.7), in: Capsule()) }
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(controller.depthState).font(.headline)
                        Text("Video: \(controller.summary.videoWritten.formatted(.number.locale(appLocale))) frames · Depth: \(controller.summary.depthWritten.formatted(.number.locale(appLocale))) samples").font(.caption).monospacedDigit()
                        if controller.summary.videoDropped + controller.summary.depthMissing > 0 { Text("Some data was missed. Check the scan results for details.").font(.caption).foregroundStyle(.yellow) }
                        Text("Mesh colors do not indicate safety").font(.caption2).foregroundStyle(.white.opacity(0.7))
                    }.padding(12).background(.black.opacity(0.65), in: RoundedRectangle(cornerRadius: 12))
                    Spacer()
                    Button { controller.stop() } label: { Label("Stop and save", systemImage: "stop.fill").font(.headline).padding(.horizontal, 14).padding(.vertical, 15) }
                        .buttonStyle(.borderedProminent).accessibilityIdentifier("stop-scan")
                }
            }.padding(22)
            if controller.phase == .saving {
                Theme.background.opacity(0.95).ignoresSafeArea()
                VStack(spacing: 16) { ProgressView().controlSize(.large); Text("Saving and validating your scan").font(.title3.bold()); Text("Checking the video, mesh, and sensor data.\nKeep the app open until saving finishes.").multilineTextAlignment(.center).foregroundStyle(.secondary) }.accessibilityIdentifier("saving-scan")
            }
        }
        .onChange(of: scenePhase) { _, phase in if phase == .background { controller.stop(reason: "background") } }
    }
}
