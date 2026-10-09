import ARKit
import RealityKit
import SwiftUI
import ZipscanCore

final class CaptureController: NSObject, ObservableObject, ARSessionDelegate, @unchecked Sendable {
    enum Phase { case preparing, scanning, saving, finished }
    @Published var phase: Phase = .preparing
    @Published var elapsed: Double = 0
    @Published var tracking = "주변을 천천히 비춰 주세요"
    @Published var depthState = "깊이 센서 준비 중"
    @Published var summary = CaptureSummary()
    @Published var thermalWarning: String?
    @Published var result: SessionManifest?
    @Published var errorMessage: String?
    let arView = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
    private let captureQueue = DispatchQueue(label: "zipscan.capture", qos: .userInteractive)
    private let session = ARSession()
    private var recorder: Recorder?
    private var chunks: [UUID: MeshChunk] = [:]
    private var settings = CaptureSettings()
    private var videoSampler = RateSampler(hz: 30)
    private var depthSampler = RateSampler(hz: 10)
    private var timer: DispatchSourceTimer?
    private var origin: Double?
    private var startedUptime: Double?
    private var warmupUptime: Double = 0
    private var frameId = 0
    private var limitedFrames = 0
    private var stopping = false
    private var lastTracking = ""
    private var lastHUD: Double = 0
    private var viewport = CGSize(width: 1920, height: 1440)
    private var oldIdleTimer = false
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid
    private var thermalObserver: NSObjectProtocol?
    var onFinish: ((SessionManifest) -> Void)?

    override init() {
        super.init()
        arView.session = session
        arView.debugOptions = [.showSceneUnderstanding]
        session.delegate = self; session.delegateQueue = captureQueue
    }

    @MainActor func start(directoryRoot: URL, settings requested: CaptureSettings = .init()) throws {
        guard ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh), ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else { throw ScanError.invalid("LiDAR를 지원하는 iPhone이 필요합니다.") }
        let configuration = ARWorldTrackingConfiguration()
        configuration.sceneReconstruction = .mesh; configuration.frameSemantics = [.sceneDepth]
        configuration.worldAlignment = .gravity
        let formats = ARWorldTrackingConfiguration.supportedVideoFormats.filter { $0.framesPerSecond >= requested.videoFps }
        guard let format = formats.min(by: {
            let a = abs($0.imageResolution.width * $0.imageResolution.height - 1920 * 1440)
            let b = abs($1.imageResolution.width * $1.imageResolution.height - 1920 * 1440)
            return a == b ? $0.framesPerSecond < $1.framesPerSecond : a < b
        }) else { throw ScanError.invalid("사용할 수 있는 카메라 포맷이 없습니다.") }
        configuration.videoFormat = format
        settings = requested; settings.imageWidth = Int(format.imageResolution.width); settings.imageHeight = Int(format.imageResolution.height); settings.arFps = format.framesPerSecond
        videoSampler = RateSampler(hz: settings.videoFps); depthSampler = RateSampler(hz: settings.depthHz)
        let manifest = SessionManifest(device: Self.hardwareModel(), osVersion: UIDevice.current.systemVersion, appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0", settings: settings)
        recorder = try Recorder(directory: directoryRoot.appendingPathComponent(manifest.id), manifest: manifest)
        recorder?.onProgress = { [weak self] stats in DispatchQueue.main.async { self?.summary = stats } }
        recorder?.onFatal = { [weak self] message in DispatchQueue.main.async { self?.errorMessage = message; self?.stop(reason: "storage_error") } }
        oldIdleTimer = UIApplication.shared.isIdleTimerDisabled; UIApplication.shared.isIdleTimerDisabled = true
        warmupUptime = ProcessInfo.processInfo.systemUptime
        thermalObserver = NotificationCenter.default.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in self?.thermalChanged() }
        let timer = DispatchSource.makeTimerSource(queue: captureQueue)
        timer.schedule(deadline: .now() + 1, repeating: 1)
        timer.setEventHandler { [weak self] in self?.tick() }
        self.timer = timer; timer.resume()
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        thermalChanged()
    }

    @MainActor func stop(reason: String = "user") {
        guard phase != .saving && phase != .finished else { return }
        phase = .saving
        if let observer = thermalObserver { NotificationCenter.default.removeObserver(observer); thermalObserver = nil }
        backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "Finish scan") { [weak self] in
            guard let self else { return }
            if self.backgroundTask != .invalid { UIApplication.shared.endBackgroundTask(self.backgroundTask); self.backgroundTask = .invalid }
        }
        captureQueue.async { [self] in
            guard !stopping else { return }; stopping = true
            session.pause(); timer?.cancel(); timer = nil
            let duration = min(settings.maxDuration, startedUptime.map { ProcessInfo.processInfo.systemUptime - $0 } ?? 0)
            recorder?.finish(meshes: Array(chunks.values), reason: reason, arFrames: frameId, limitedFrames: limitedFrames, duration: duration) { [weak self] manifest in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.result = manifest; self.phase = .finished
                    UIApplication.shared.isIdleTimerDisabled = self.oldIdleTimer
                    if self.backgroundTask != .invalid { UIApplication.shared.endBackgroundTask(self.backgroundTask); self.backgroundTask = .invalid }
                    if let observer = self.thermalObserver { NotificationCenter.default.removeObserver(observer); self.thermalObserver = nil }
                    self.onFinish?(manifest)
                }
            }
            chunks.removeAll()
        }
    }

    private func tick() {
        guard !stopping else { return }
        let uptime = ProcessInfo.processInfo.systemUptime
        if let start = startedUptime {
            let elapsed = uptime - start
            DispatchQueue.main.async { self.elapsed = min(elapsed, self.settings.maxDuration) }
            if elapsed >= settings.maxDuration { requestStop("time_limit") }
        } else if uptime - warmupUptime >= 30 { requestStop("tracking_initialization_timeout") }
        if let directory = recorder?.directory, Files.available(directory) < 1_000_000_000 { requestStop("low_storage") }
    }

    func updateViewport(_ size: CGSize) {
        guard size.width > 0, size.height > 0 else { return }
        captureQueue.async { self.viewport = size }
    }

    private func requestStop(_ reason: String) { DispatchQueue.main.async { [weak self] in self?.stop(reason: reason) } }

    private func thermalChanged() {
        let state = ProcessInfo.processInfo.thermalState
        recorder?.event(CaptureEvent("thermal", message: "\(state.rawValue)"))
        if state == .serious { thermalWarning = "기기가 뜨겁습니다. 잠시 후 촬영을 마쳐 주세요." }
        else if state == .critical { thermalWarning = "발열로 수집을 종료합니다."; requestStop("thermal_critical") }
        else { thermalWarning = nil }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard !stopping, let recorder else { return }
        let state = Self.trackingInfo(frame.camera.trackingState)
        let stateKey = state.0 + (state.1 ?? "")
        if stateKey != lastTracking {
            recorder.event(CaptureEvent("tracking", message: stateKey, timestamp: frame.timestamp))
            lastTracking = stateKey
        }
        if frame.timestamp - lastHUD >= 0.5 {
            lastHUD = frame.timestamp
            let ready = frame.sceneDepth?.confidenceMap != nil
            DispatchQueue.main.async {
                self.tracking = state.0 == "normal" ? "추적 정상" : "천천히 이동하세요"
                self.depthState = ready ? "깊이 수집 중" : "일부 공간 데이터가 저장되지 않았습니다"
            }
        }
        if origin == nil {
            guard state.0 == "normal", frame.sceneDepth?.confidenceMap != nil else { return }
            origin = frame.timestamp; startedUptime = ProcessInfo.processInfo.systemUptime
            DispatchQueue.main.async { if self.phase == .preparing { self.phase = .scanning } }
        }
        guard frame.timestamp - origin! < settings.maxDuration else { requestStop("time_limit"); return }
        frameId += 1
        if state.0 != "normal" { limitedFrames += 1 }
        let wantsVideo = videoSampler.take(frame.timestamp), wantsDepth = depthSampler.take(frame.timestamp)
        guard wantsVideo || wantsDepth else { return }
        let admitted = recorder.reserveImageSlot()
        let transform = frame.displayTransform(for: .landscapeRight, viewportSize: viewport)
        let record = FrameRecord(frameId: frameId, arTimestamp: frame.timestamp, cameraTransform: Geometry.rows(frame.camera.transform), intrinsics: Geometry.rows(frame.camera.intrinsics), imageWidth: Int(frame.camera.imageResolution.width), imageHeight: Int(frame.camera.imageResolution.height), trackingState: state.0, trackingReason: state.1, displayTransform: [transform.a, transform.b, transform.c, transform.d, transform.tx, transform.ty].map(Double.init), displayViewport: [Double(viewport.width), Double(viewport.height)])
        var depth: CapturedDepth?, depthError: String?
        if wantsDepth {
            if !admitted { depthError = "queue_full" }
            else {
                do { depth = try Self.copyDepth(frame.sceneDepth) }
                catch { depthError = error.localizedDescription }
            }
        }
        recorder.submit(CapturePacket(record: record, wantsVideo: wantsVideo, wantsDepth: wantsDepth, image: admitted && wantsVideo ? frame.capturedImage : nil, depth: depth, depthError: depthError, ownsImageSlot: admitted))
    }

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) { updateMeshes(anchors) }
    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        guard !stopping else { return }; for anchor in anchors { chunks.removeValue(forKey: anchor.identifier) }
    }
    func sessionWasInterrupted(_ session: ARSession) { requestStop("ar_interrupted") }
    func session(_ session: ARSession, didFailWithError error: Error) {
        recorder?.event(CaptureEvent("ar_error", message: error.localizedDescription)); requestStop("ar_failed")
    }
    private func updateMeshes(_ anchors: [ARAnchor]) {
        guard !stopping else { return }
        for anchor in anchors.compactMap({ $0 as? ARMeshAnchor }) {
            let source = anchor.geometry.vertices, faces = anchor.geometry.faces
            guard source.format == .float3, faces.indexCountPerPrimitive == 3, [2, 4].contains(faces.bytesPerIndex) else {
                recorder?.event(CaptureEvent("mesh_error", message: "지원하지 않는 메쉬 버퍼 포맷")); requestStop("mesh_error"); return
            }
            let base = source.buffer.contents().advanced(by: source.offset)
            let vertices: [SIMD3<Float>] = (0..<source.count).map { index in
                let ptr = base.advanced(by: index * source.stride)
                return SIMD3(ptr.loadUnaligned(as: Float.self), ptr.loadUnaligned(fromByteOffset: 4, as: Float.self), ptr.loadUnaligned(fromByteOffset: 8, as: Float.self))
            }
            let indexBase = faces.buffer.contents()
            let indices: [UInt32] = (0..<(faces.count * 3)).map { index in
                let ptr = indexBase.advanced(by: index * faces.bytesPerIndex)
                return faces.bytesPerIndex == 4 ? ptr.loadUnaligned(as: UInt32.self) : UInt32(ptr.loadUnaligned(as: UInt16.self))
            }
            chunks[anchor.identifier] = MeshChunk(vertices: vertices, indices: indices, transform: anchor.transform)
        }
    }

    static func copyDepth(_ scene: ARDepthData?) throws -> CapturedDepth {
        guard let scene, let confidence = scene.confidenceMap else { throw ScanError.invalid("scene_depth_or_confidence_unavailable") }
        let depth = scene.depthMap
        let width = CVPixelBufferGetWidth(depth), height = CVPixelBufferGetHeight(depth)
        guard CVPixelBufferGetPixelFormatType(depth) == kCVPixelFormatType_DepthFloat32,
              CVPixelBufferGetPixelFormatType(confidence) == kCVPixelFormatType_OneComponent8,
              CVPixelBufferGetWidth(confidence) == width, CVPixelBufferGetHeight(confidence) == height else { throw ScanError.invalid("depth_format_mismatch") }
        guard CVPixelBufferLockBaseAddress(depth, .readOnly) == kCVReturnSuccess else { throw ScanError.invalid("depth_lock_failed") }
        defer { CVPixelBufferUnlockBaseAddress(depth, .readOnly) }
        guard CVPixelBufferLockBaseAddress(confidence, .readOnly) == kCVReturnSuccess else { throw ScanError.invalid("confidence_lock_failed") }
        defer { CVPixelBufferUnlockBaseAddress(confidence, .readOnly) }
        guard let d = CVPixelBufferGetBaseAddress(depth), let c = CVPixelBufferGetBaseAddress(confidence) else { throw ScanError.invalid("depth_buffer_unavailable") }
        return try CapturedDepth(width: width, height: height, depth: Files.packRows(base: d, width: width, height: height, bytesPerPixel: 4, bytesPerRow: CVPixelBufferGetBytesPerRow(depth)), confidence: Files.packRows(base: c, width: width, height: height, bytesPerPixel: 1, bytesPerRow: CVPixelBufferGetBytesPerRow(confidence)))
    }
    private static func trackingInfo(_ state: ARCamera.TrackingState) -> (String, String?) {
        switch state {
        case .normal: return ("normal", nil)
        case .notAvailable: return ("not_available", nil)
        case .limited(let reason):
            switch reason {
            case .initializing: return ("limited", "initializing")
            case .excessiveMotion: return ("limited", "excessive_motion")
            case .insufficientFeatures: return ("limited", "insufficient_features")
            case .relocalizing: return ("limited", "relocalizing")
            @unknown default: return ("limited", "unknown")
            }
        }
    }
    private static func hardwareModel() -> String {
        var info = utsname(); uname(&info)
        return withUnsafePointer(to: &info.machine) { $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) } }
    }
    deinit { session.pause(); timer?.cancel(); if let observer = thermalObserver { NotificationCenter.default.removeObserver(observer) } }
}

final class CameraSurface: UIView {
    let controller: CaptureController
    init(controller: CaptureController) {
        self.controller = controller
        super.init(frame: .zero)
        addSubview(controller.arView)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
    override func layoutSubviews() {
        super.layoutSubviews()
        controller.arView.frame = bounds
        controller.updateViewport(bounds.size)
    }
}

struct CameraView: UIViewRepresentable {
    let controller: CaptureController
    func makeUIView(context: Context) -> CameraSurface { CameraSurface(controller: controller) }
    func updateUIView(_ uiView: CameraSurface, context: Context) {}
}
