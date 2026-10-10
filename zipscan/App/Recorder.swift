import ARKit
import AVFoundation
import ZipscanCore

struct CapturedDepth {
    let width: Int
    let height: Int
    let depth: Data
    let confidence: Data
}

struct CapturePacket {
    var record: FrameRecord
    let wantsVideo: Bool
    let wantsDepth: Bool
    let image: CVPixelBuffer?
    let depth: CapturedDepth?
    let depthError: String?
    let ownsImageSlot: Bool
}

/// All file and encoder state belongs to `queue`. ARKit never waits for disk or the encoder.
final class Recorder: @unchecked Sendable {
    let directory: URL
    private let queue = DispatchQueue(label: "zipscan.writer", qos: .userInitiated)
    private let imageSlots = DispatchSemaphore(value: 4)
    private let metadataSlots = DispatchSemaphore(value: 128)
    private let overflowLock = NSLock()
    private var overflow = 0
    private var overflowVideo = 0
    private var overflowDepth = 0
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private let frames: JSONLinesWriter
    private let depthIndex: JSONLinesWriter
    private let events: JSONLinesWriter
    private let depthFile: FileHandle
    private let confidenceFile: FileHandle
    private var depthOffset: UInt64 = 0
    private var confidenceOffset: UInt64 = 0
    private var manifest: SessionManifest
    private var failures: [String] = []
    private var finishing = false
    private var lastProgress: Double = -1
    private var lastFlush: Double = -1
    var onProgress: ((CaptureSummary) -> Void)?
    var onFatal: ((String) -> Void)?

    init(directory: URL, manifest: SessionManifest) throws {
        self.directory = directory; self.manifest = manifest
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
        frames = try JSONLinesWriter(directory.appendingPathComponent("frames.jsonl"))
        depthIndex = try JSONLinesWriter(directory.appendingPathComponent("depth-index.jsonl"))
        events = try JSONLinesWriter(directory.appendingPathComponent("events.jsonl"))
        for name in ["depth.bin", "confidence.bin"] {
            guard FileManager.default.createFile(atPath: directory.appendingPathComponent(name).path, contents: nil) else { throw ScanError.invalid("Could not create a binary data file") }
        }
        depthFile = try FileHandle(forWritingTo: directory.appendingPathComponent("depth.bin"))
        confidenceFile = try FileHandle(forWritingTo: directory.appendingPathComponent("confidence.bin"))
        try events.append(CaptureEvent("session_created", message: "Preparing to scan"))
    }

    func reserveImageSlot() -> Bool { imageSlots.wait(timeout: .now()) == .success }

    func submit(_ packet: CapturePacket) {
        guard metadataSlots.wait(timeout: .now()) == .success else {
            if packet.ownsImageSlot { imageSlots.signal() }
            overflowLock.lock()
            overflow += 1; overflowVideo += packet.wantsVideo ? 1 : 0; overflowDepth += packet.wantsDepth ? 1 : 0
            let first = overflow == 1
            overflowLock.unlock()
            if first { onFatal?("The metadata queue is full.") }
            return
        }
        queue.async { [self] in
            defer { metadataSlots.signal(); if packet.ownsImageSlot { imageSlots.signal() } }
            autoreleasepool {
                do { try write(packet) } catch { fail(error) }
            }
        }
    }

    func event(_ event: CaptureEvent) {
        queue.async { [self] in do { try events.append(event) } catch { fail(error) } }
    }

    private func fail(_ error: Error) {
        if failures.count < 20 { failures.append(error.localizedDescription) }
        if failures.count == 1 {
            try? events.append(CaptureEvent("storage_error", message: error.localizedDescription))
            onFatal?(error.localizedDescription)
        }
    }

    private func configureVideo(_ image: CVPixelBuffer) throws {
        let width = CVPixelBufferGetWidth(image), height = CVPixelBufferGetHeight(image)
        manifest.settings.imageWidth = width; manifest.settings.imageHeight = height
        let writer = try AVAssetWriter(outputURL: directory.appendingPathComponent("video.mp4"), fileType: .mp4)
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width, AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: manifest.settings.videoBitrate,
                AVVideoExpectedSourceFrameRateKey: manifest.settings.videoFps,
                AVVideoMaxKeyFrameIntervalKey: manifest.settings.videoFps * 2,
                AVVideoAllowFrameReorderingKey: false
            ]
        ])
        input.mediaTimeScale = 1_000_000
        input.expectsMediaDataInRealTime = true
        input.transform = .identity
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: CVPixelBufferGetPixelFormatType(image),
            kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height
        ])
        guard writer.canAdd(input) else { throw ScanError.invalid("Could not configure the video encoder.") }
        writer.add(input)
        guard writer.startWriting() else { throw writer.error ?? ScanError.invalid("Could not start recording video") }
        writer.startSession(atSourceTime: .zero)
        self.writer = writer; self.input = input; self.adaptor = adaptor
        try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
    }

    private func write(_ packet: CapturePacket) throws {
        var record = packet.record
        if manifest.timeOrigin == nil {
            manifest.timeOrigin = record.arTimestamp
            try events.append(CaptureEvent("capture_started", message: "First captured frame", timestamp: record.arTimestamp))
            try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
        }
        let elapsed = record.arTimestamp - manifest.timeOrigin!
        manifest.summary.duration = max(manifest.summary.duration, elapsed)
        if packet.wantsVideo {
            manifest.summary.videoExpected += 1
            if let image = packet.image {
                if writer == nil { try configureVideo(image) }
                if input?.isReadyForMoreMediaData == true {
                    let pts = CMTime(seconds: elapsed, preferredTimescale: 1_000_000)
                    if adaptor?.append(image, withPresentationTime: pts) == true {
                        record.videoPts = pts.seconds; record.videoStatus = "written"
                        manifest.summary.videoWritten += 1
                    } else {
                        record.videoStatus = "encode_failed"
                        if let error = writer?.error { fail(error) }
                    }
                } else { record.videoStatus = "encoder_busy" }
            } else { record.videoStatus = "queue_full" }
            if record.videoStatus != "written" {
                manifest.summary.videoDropped += 1
                try events.append(CaptureEvent("video_dropped", message: record.videoStatus, timestamp: record.arTimestamp, frameId: record.frameId))
            }
        }
        if packet.wantsDepth {
            manifest.summary.depthExpected += 1
            var index = DepthRecord(frameId: record.frameId, arTimestamp: record.arTimestamp, missingReason: packet.depthError ?? "scene_depth_unavailable")
            if let depth = packet.depth {
                index.width = depth.width; index.height = depth.height
                do {
                    try depthFile.write(contentsOf: depth.depth)
                    try confidenceFile.write(contentsOf: depth.confidence)
                    index.depthOffset = depthOffset; index.depthLength = depth.depth.count
                    index.confidenceOffset = confidenceOffset; index.confidenceLength = depth.confidence.count
                    index.intrinsics = Geometry.scaledIntrinsics(record.intrinsics, imageWidth: record.imageWidth, imageHeight: record.imageHeight, depthWidth: depth.width, depthHeight: depth.height)
                    index.missingReason = nil
                    depthOffset += UInt64(depth.depth.count); confidenceOffset += UInt64(depth.confidence.count)
                    manifest.summary.depthWritten += 1
                } catch {
                    try? depthFile.truncate(atOffset: depthOffset); try? depthFile.seek(toOffset: depthOffset)
                    try? confidenceFile.truncate(atOffset: confidenceOffset); try? confidenceFile.seek(toOffset: confidenceOffset)
                    index.missingReason = "storage_error"; fail(error)
                }
            }
            if index.missingReason != nil {
                manifest.summary.depthMissing += 1
                try events.append(CaptureEvent("depth_missing", message: index.missingReason!, timestamp: record.arTimestamp, frameId: record.frameId))
            }
            try depthIndex.append(index)
        }
        try frames.append(record)
        if elapsed - lastFlush >= 2 {
            try frames.flush(); try depthIndex.flush(); try events.flush()
            try depthFile.synchronize(); try confidenceFile.synchronize()
            lastFlush = elapsed
        }
        if elapsed - lastProgress >= 0.5 {
            lastProgress = elapsed; onProgress?(manifest.summary)
        }
    }

    func finish(meshes: [MeshChunk], reason: String, arFrames: Int, limitedFrames: Int, duration: Double, completion: @escaping (SessionManifest) -> Void) {
        queue.async { [self] in
            guard !finishing else { return }; finishing = true
            manifest.status = .finalizing; manifest.stopReason = reason; manifest.endedAt = Date()
            manifest.summary.arFrames = arFrames; manifest.summary.trackingLimitedFrames = limitedFrames
            manifest.summary.duration = duration
            overflowLock.lock()
            let lost = overflow, lostVideo = overflowVideo, lostDepth = overflowDepth
            overflowLock.unlock()
            if lost > 0 {
                failures.append("metadata_overflow: \(lost) frames omitted")
                manifest.summary.videoExpected += lostVideo; manifest.summary.videoDropped += lostVideo
                manifest.summary.depthExpected += lostDepth; manifest.summary.depthMissing += lostDepth
            }
            do {
                try events.append(CaptureEvent("capture_stopped", message: reason, count: lost))
                try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
                let counts = try OBJ.write(meshes, to: directory.appendingPathComponent("mesh.obj"))
                manifest.summary.meshVertices = counts.vertices; manifest.summary.meshFaces = counts.faces
            } catch { fail(error) }
            if let writer, writer.status == .writing {
                input?.markAsFinished()
                writer.finishWriting { [self] in queue.async { self.finalize(completion) } }
            } else { finalize(completion) }
        }
    }

    private func finalize(_ completion: @escaping (SessionManifest) -> Void) {
        if let writer, writer.status != .completed { failures.append(writer.error?.localizedDescription ?? "Could not finalize the video") }
        for operation in [{ try self.frames.close() }, { try self.depthIndex.close() }, { try self.events.close() },
                          { try self.depthFile.synchronize(); try self.depthFile.close() }, { try self.confidenceFile.synchronize(); try self.confidenceFile.close() }] {
            do { try operation() } catch { failures.append(error.localizedDescription) }
        }
        manifest.errors = failures
        let draft = manifest, directory = directory
        Task {
            var final = draft
            let report = await PackageValidator.validate(directory, manifest: draft)
            final.errors += report.issues
            final.warnings = report.warnings
            let normalStop = ["user", "time_limit", "debug_smoke"].contains(final.stopReason ?? "")
            if !normalStop { final.warnings.append("Scan ended early: \(final.stopReason ?? "unknown")") }
            final.status = final.errors.isEmpty && final.summary.videoDropped == 0 && final.summary.depthMissing == 0 && normalStop ? .complete : .partial
            if final.summary.videoWritten == 0 && final.summary.depthWritten == 0 && final.summary.meshFaces == 0 { final.status = .failed }
            do {
                try JSON.save(report, to: directory.appendingPathComponent("validation.json"))
                final.files = try Files.payloads(directory)
                final.missingFiles = Files.required.filter { name in !final.files.contains { $0.name == name } }
                if !final.missingFiles.isEmpty && final.status == .complete { final.status = .partial }
                try JSON.save(final, to: directory.appendingPathComponent("manifest.json"))
            } catch { if final.status != .failed { final.status = .partial }; final.errors.append(error.localizedDescription); try? JSON.save(final, to: directory.appendingPathComponent("manifest.json")) }
            completion(final)
        }
    }
}
