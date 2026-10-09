import SwiftUI
import AVFoundation
import ARKit
import ZipscanCore

@main struct ZipscanApp: App {
    var body: some Scene {
        WindowGroup { LibraryScreen().preferredColorScheme(.dark).tint(Theme.accent) }
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

func sessionDateLabel(_ date: Date) -> String { date.formatted(.dateTime.year().month(.twoDigits).day(.twoDigits).hour().minute().locale(Locale(identifier: "ko_KR"))) }

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
                Text("현장을 담고,\n공간을 남기다.").font(.system(size: 30, weight: .bold)).fixedSize(horizontal: false, vertical: true)
                Text("영상과 공간을 하나의 기록으로.\nLiDAR로 실내를 천천히 스캔하세요.").font(.subheadline).foregroundStyle(.secondary)
                Spacer(minLength: 0)
                Button { newScan = true } label: { Label("새 스캔", systemImage: "plus").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12) }
                    .buttonStyle(.borderedProminent).accessibilityIdentifier("new-scan").disabled(library.loading)
                Text("iPhone LiDAR · 최대 10분").font(.caption).foregroundStyle(.secondary)
            }.frame(width: 265)
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text("스캔 기록").font(.title3.bold()); Text("\(library.sessions.count)").foregroundStyle(.secondary); Spacer(); if library.loading { ProgressView() } }
                if library.sessions.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "square.stack.3d.up").font(.system(size: 40)).foregroundStyle(Theme.cyan)
                        Text(library.loading ? "기록을 확인하고 있습니다" : "첫 공간을 기록해 보세요").font(.headline)
                        Text("완료된 스캔의 3D와 영상을 여기서 확인합니다.").font(.caption).foregroundStyle(.secondary)
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
                                                Text("\(timeLabel(session.manifest.summary.duration)) · \(session.manifest.summary.meshFaces.formatted())개 메쉬 면").font(.caption).foregroundStyle(.secondary)
                                            }
                                            Spacer()
                                            Text(session.manifest.status.title).font(.caption.bold()).foregroundStyle(Theme.status(session.manifest.status))
                                        }.contentShape(Rectangle())
                                    }.buttonStyle(.plain).accessibilityIdentifier("session-\(session.id)")
                                    Button(role: .destructive) { deleting = session } label: { Image(systemName: "trash").padding(10) }.accessibilityLabel("세션 삭제").accessibilityIdentifier("delete-session-\(session.id)")
                                }.padding(12).background(Theme.panel, in: RoundedRectangle(cornerRadius: 16))
                            }
                        }
                    }
                }
                if let error = library.error { Text(error).font(.caption).foregroundStyle(.yellow).lineLimit(2) }
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
        .alert("이 스캔을 삭제할까요?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
            Button("취소", role: .cancel) { deleting = nil }
            Button("삭제", role: .destructive) { if let session = deleting { Task { await library.delete(session) } }; deleting = nil }
        } message: { Text("이 기기의 영상·공간 데이터와 내보낸 ZIP이 삭제됩니다. 다른 곳에 공유한 파일은 유지됩니다.") }
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
                        Text("촬영 준비").font(.largeTitle.bold())
                        Text("가로로 들고,\n천천히 걸어 주세요.").font(.title2.weight(.medium))
                        Text("벽·바닥·주변 물체를 여러 방향에서 비춰 주세요. 손으로 후면 카메라와 LiDAR를 가리지 마세요.").foregroundStyle(.secondary)
                        Spacer(minLength: 0)
                        Button("돌아가기") { dismiss() }.buttonStyle(.bordered)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 14) {
                        readiness("LiDAR 공간 수집", detail: supported ? "지원하는 iPhone" : "LiDAR 지원 iPhone이 필요합니다", ok: supported)
                        readiness("저장 공간", detail: "\(ByteCountFormatter.string(fromByteCount: Files.available(library.root), countStyle: .file)) 사용 가능 · 최소 6GB", ok: Files.available(library.root) >= 6_000_000_000)
                        readiness("카메라", detail: "영상과 공간 데이터 수집 · 음성 제외", ok: AVCaptureDevice.authorizationStatus(for: .video) != .denied)
                        Text("최대 10분 후 자동 저장합니다. 메쉬의 색은 위험도나 안전 판정을 뜻하지 않습니다.").font(.caption).foregroundStyle(.secondary)
                        if let error { Text(error).font(.caption).foregroundStyle(.yellow) }
                        Button { Task { await start() } } label: {
                            HStack { if checking { ProgressView() }; Text(checking ? "확인 중" : "스캔 시작").bold() }.frame(maxWidth: .infinity).padding(.vertical, 10)
                        }.buttonStyle(.borderedProminent).disabled(checking || !supported).accessibilityIdentifier("start-scan")
                        if AVCaptureDevice.authorizationStatus(for: .video) == .denied {
                            Button("설정에서 카메라 허용") { if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) } }.font(.caption)
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
            guard Files.available(library.root) >= 6_000_000_000 else { throw ScanError.invalid("촬영을 시작하려면 6GB 이상의 저장 공간이 필요합니다.") }
            let permission = AVCaptureDevice.authorizationStatus(for: .video)
            let granted: Bool
            if permission == .notDetermined { granted = await AVCaptureDevice.requestAccess(for: .video) }
            else { granted = permission == .authorized }
            guard granted else { throw ScanError.invalid("설정에서 카메라 접근을 허용해 주세요.") }
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
                    HStack(spacing: 9) { Circle().fill(controller.phase == .scanning ? .red : .yellow).frame(width: 9, height: 9); Text(controller.phase == .preparing ? "센서 준비 중" : "수집 중").bold(); Text(timeLabel(controller.elapsed)).monospacedDigit() }
                        .padding(12).background(.black.opacity(0.6), in: Capsule())
                    Spacer()
                    Label(controller.tracking, systemImage: "location.viewfinder").font(.subheadline).padding(12).background(.black.opacity(0.6), in: Capsule())
                }
                Spacer()
                if let warning = controller.thermalWarning { Text(warning).foregroundStyle(.yellow).padding(8).background(.black.opacity(0.7), in: Capsule()) }
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(controller.depthState).font(.headline)
                        Text("영상 \(controller.summary.videoWritten.formatted()) 프레임 · 깊이 \(controller.summary.depthWritten.formatted())회").font(.caption).monospacedDigit()
                        if controller.summary.videoDropped + controller.summary.depthMissing > 0 { Text("일부 데이터가 누락되었습니다. 결과에서 확인해 주세요.").font(.caption).foregroundStyle(.yellow) }
                        Text("메쉬 색은 안전 판정이 아닙니다").font(.caption2).foregroundStyle(.white.opacity(0.7))
                    }.padding(12).background(.black.opacity(0.65), in: RoundedRectangle(cornerRadius: 12))
                    Spacer()
                    Button { controller.stop() } label: { Label("종료하고 저장", systemImage: "stop.fill").font(.headline).padding(.horizontal, 14).padding(.vertical, 15) }
                        .buttonStyle(.borderedProminent).accessibilityIdentifier("stop-scan")
                }
            }.padding(22)
            if controller.phase == .saving {
                Theme.background.opacity(0.95).ignoresSafeArea()
                VStack(spacing: 16) { ProgressView().controlSize(.large); Text("스캔을 저장하고 검증하고 있습니다").font(.title3.bold()); Text("영상·메쉬·센서 데이터의 연결을 확인합니다.\n완료될 때까지 앱을 열어 두세요.").multilineTextAlignment(.center).foregroundStyle(.secondary) }.accessibilityIdentifier("saving-scan")
            }
        }
        .onChange(of: scenePhase) { _, phase in if phase == .background { controller.stop(reason: "background") } }
    }
}
