import XCTest
import AVFoundation
import ZIPFoundation
import simd
@testable import ZipscanCore

final class CoreTests: XCTestCase {
    private var directory: URL!
    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("zipscan-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
    override func tearDownWithError() throws { try FileManager.default.removeItem(at: directory) }

    func testSamplingForTenMinutesDoesNotDrift() {
        var video = RateSampler(hz: 30), depth = RateSampler(hz: 10)
        var videoCount = 0, depthCount = 0
        for i in 0..<36_000 {
            let timestamp = 54_123.987 + Double(i) / 60
            if video.take(timestamp) { videoCount += 1 }
            if depth.take(timestamp) { depthCount += 1 }
        }
        XCTAssertEqual(videoCount, 18_000); XCTAssertEqual(depthCount, 6_000)
        XCTAssertTrue(video.take(54_800)); XCTAssertFalse(video.take(54_800))
    }

    func testMatrixConventionAndWorldMeshRoundTrip() throws {
        var matrix = matrix_identity_float4x4; matrix.columns.3 = SIMD4(2, 3, -4, 1)
        XCTAssertEqual(Geometry.rows(matrix)[0], [1, 0, 0, 2])
        let chunk = MeshChunk(vertices: [SIMD3(0, 0, 0), SIMD3(1, 0, 0), SIMD3(0, 1, 0)], indices: [0, 1, 2], transform: matrix)
        let url = directory.appendingPathComponent("mesh.obj")
        let counts = try OBJ.write([chunk, chunk], to: url)
        XCTAssertEqual(counts.vertices, 6); XCTAssertEqual(counts.faces, 2)
        let read = try OBJ.read(url)
        XCTAssertEqual(read.vertices[0], SIMD3(2, 3, -4)); XCTAssertEqual(read.indices, [0, 1, 2, 3, 4, 5])
    }

    func testDepthPaddingAndIntrinsics() throws {
        let raw: [UInt8] = [1, 2, 3, 4, 99, 99, 5, 6, 7, 8, 99, 99]
        let packed = try raw.withUnsafeBytes { try Files.packRows(base: $0.baseAddress!, width: 2, height: 2, bytesPerPixel: 2, bytesPerRow: 6) }
        XCTAssertEqual(Array(packed), [1, 2, 3, 4, 5, 6, 7, 8])
        XCTAssertEqual(Geometry.scaledIntrinsics([[100, 0, 32], [0, 120, 24], [0, 0, 1]], imageWidth: 64, imageHeight: 48, depthWidth: 2, depthHeight: 2), [[3.125, 0, 1], [0, 5, 1], [0, 0, 1]])
    }

    func testTimestampFilenameUsesCaptureStartInKorea() throws {
        var manifest = SessionManifest(id: "b2b88be1-f4db-4a5f-8a51-d900b632c421", device: "test", osVersion: "test", appVersion: "test")
        manifest.startedAt = ISO8601DateFormatter().date(from: "2026-10-09T02:30:15Z")!
        XCTAssertEqual(manifest.exportFileName, "20261009-113015_b2b88be1-f4db-4a5f-8a51-d900b632c421.zip")
        let decoded = try JSON.decoder().decode(SessionManifest.self, from: JSON.encoder().encode(manifest))
        XCTAssertEqual(decoded.exportFileName, manifest.exportFileName)
    }

    func testTruncatedJSONLinesAreRejected() throws {
        let url = directory.appendingPathComponent("frames.jsonl")
        try Data("{\"a\":1}\n{\"a\":".utf8).write(to: url)
        var lines = 0
        XCTAssertThrowsError(try Files.forEachLine(url) { _ in lines += 1 })
        XCTAssertEqual(lines, 1)
    }

    func testValidPackageVideoAndStreamingExport() async throws {
        var manifest = try await makeFixture()
        let report = await PackageValidator.validate(directory, manifest: manifest)
        XCTAssertTrue(report.passed, report.issues.joined(separator: "; "))
        XCTAssertEqual(report.videoSampleCount, 3); XCTAssertEqual(report.depthCount, 1)
        try JSON.save(report, to: directory.appendingPathComponent("validation.json"))
        manifest.files = try Files.payloads(directory)
        try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
        let checked = await PackageValidator.validate(directory, manifest: manifest, checkHashes: true)
        XCTAssertTrue(checked.passed, checked.issues.joined(separator: "; "))
        let target = directory.appendingPathComponent("exports")
        let zip = try Exporter.export(session: directory, destination: target)
        XCTAssertEqual(zip.lastPathComponent, manifest.exportFileName)
        let archive = try Archive(url: zip, accessMode: .read)
        XCTAssertEqual(Set(archive.map(\.path)), Set(Files.required + ["manifest.json"]))
        XCTAssertEqual(try Exporter.export(session: directory, destination: target), zip)
        var changed = try Data(contentsOf: directory.appendingPathComponent("depth.bin")); changed[0] ^= 1
        try changed.write(to: directory.appendingPathComponent("depth.bin"))
        XCTAssertThrowsError(try Exporter.export(session: directory, destination: target))
        XCTAssertTrue(FileManager.default.fileExists(atPath: zip.path), "이전 ZIP은 실패 시 보존되어야 합니다")
    }

    func testCorruptDepthReferenceAndMissingConfidenceAreDetected() async throws {
        let manifest = try await makeFixture()
        let url = directory.appendingPathComponent("depth-index.jsonl")
        var record: DepthRecord!
        try Files.forEachLine(url) { record = try JSON.decoder().decode(DepthRecord.self, from: $0) }
        record.depthOffset = 4
        let writer = try JSONLinesWriter(url); try writer.append(record); try writer.close()
        var report = await PackageValidator.validate(directory, manifest: manifest)
        XCTAssertTrue(report.issues.contains { $0.contains("바이너리 범위") })
        try FileManager.default.removeItem(at: directory.appendingPathComponent("confidence.bin"))
        report = await PackageValidator.validate(directory, manifest: manifest)
        XCTAssertFalse(report.passed)
    }

    func testUnwrittenFrameCannotClaimVideoPTS() async throws {
        let manifest = try await makeFixture()
        let url = directory.appendingPathComponent("frames.jsonl")
        var frames: [FrameRecord] = []
        try Files.forEachLine(url) { frames.append(try JSON.decoder().decode(FrameRecord.self, from: $0)) }
        frames[0].videoStatus = "queue_full"
        let writer = try JSONLinesWriter(url); for frame in frames { try writer.append(frame) }; try writer.close()
        let report = await PackageValidator.validate(directory, manifest: manifest)
        XCTAssertTrue(report.issues.contains { $0.contains("저장되지 않은 프레임") })
    }

    func testMissingMeshIsPartialEvidenceNotValidPackage() async throws {
        let manifest = try await makeFixture()
        try FileManager.default.removeItem(at: directory.appendingPathComponent("mesh.obj"))
        let report = await PackageValidator.validate(directory, manifest: manifest)
        XCTAssertFalse(report.passed); XCTAssertTrue(report.issues.contains { $0.contains("메쉬 검증") })
        XCTAssertEqual(report.videoSampleCount, 3)
    }

    func testInterruptedSessionRecoveryKeepsEvidenceAndNeverClaimsCompletion() async throws {
        var manifest = try await makeFixture()
        manifest.status = .recording
        manifest.summary = CaptureSummary()
        try JSON.save(manifest, to: directory.appendingPathComponent("manifest.json"))
        let recovered = try await SessionRecovery.recover(directory)
        XCTAssertEqual(recovered.status, .partial)
        XCTAssertEqual(recovered.summary.videoWritten, 3)
        XCTAssertEqual(recovered.summary.depthWritten, 1)
        XCTAssertGreaterThan(recovered.summary.duration, 0.06)
        XCTAssertTrue(recovered.errors.isEmpty)
        XCTAssertEqual(recovered.stopReason, "recovered_after_interruption")
        let checked = await PackageValidator.validate(directory, manifest: recovered, checkHashes: true)
        XCTAssertTrue(checked.passed, checked.issues.joined(separator: "; "))
        let again = try await SessionRecovery.recover(directory)
        XCTAssertEqual(again.files, recovered.files)
    }

    private func makeFixture() async throws -> SessionManifest {
        var manifest = SessionManifest(device: "fixture", osVersion: "test", appVersion: "0.1.0")
        manifest.status = .complete; manifest.timeOrigin = 1000
        manifest.settings.imageWidth = 64; manifest.settings.imageHeight = 48; manifest.settings.arFps = 30
        manifest.summary.videoExpected = 3; manifest.summary.videoWritten = 3
        manifest.summary.depthExpected = 1; manifest.summary.depthWritten = 1
        let frames = try JSONLinesWriter(directory.appendingPathComponent("frames.jsonl"))
        for i in 0..<3 {
            var frame = FrameRecord(frameId: i + 1, arTimestamp: 1000 + [0.0, 0.033823, 0.068827][i], cameraTransform: Geometry.rows(matrix_identity_float4x4), intrinsics: [[100, 0, 32], [0, 120, 24], [0, 0, 1]], imageWidth: 64, imageHeight: 48, trackingState: "normal", trackingReason: nil, displayTransform: [1, 0, 0, 1, 0, 0])
            frame.videoStatus = "written"; frame.videoPts = CMTime(seconds: [0.0, 0.033823, 0.068827][i], preferredTimescale: 1_000_000).seconds
            try frames.append(frame)
        }
        try frames.close()
        var depth = DepthRecord(frameId: 1, arTimestamp: 1000, width: 2, height: 2)
        depth.depthOffset = 0; depth.depthLength = 16; depth.confidenceOffset = 0; depth.confidenceLength = 4
        depth.intrinsics = [[3.125, 0, 1], [0, 5, 1], [0, 0, 1]]
        let depthWriter = try JSONLinesWriter(directory.appendingPathComponent("depth-index.jsonl")); try depthWriter.append(depth); try depthWriter.close()
        let values: [Float] = [1, 2, 3, 4]
        try values.withUnsafeBufferPointer { try Data(buffer: $0).write(to: directory.appendingPathComponent("depth.bin")) }
        try Data([2, 2, 1, 0]).write(to: directory.appendingPathComponent("confidence.bin"))
        _ = try OBJ.write([MeshChunk(vertices: [SIMD3(0, 0, 0), SIMD3(1, 0, 0), SIMD3(0, 1, 0)], indices: [0, 1, 2])], to: directory.appendingPathComponent("mesh.obj"))
        let events = try JSONLinesWriter(directory.appendingPathComponent("events.jsonl")); try events.append(CaptureEvent("capture_stopped", message: "user")); try events.close()
        try await makeVideo(directory.appendingPathComponent("video.mp4"))
        return manifest
    }

    private func makeVideo(_ url: URL) async throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: [AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: 64, AVVideoHeightKey: 48, AVVideoCompressionPropertiesKey: [AVVideoAllowFrameReorderingKey: false]])
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA, kCVPixelBufferWidthKey as String: 64, kCVPixelBufferHeightKey as String: 48])
        input.mediaTimeScale = 1_000_000
        writer.add(input); XCTAssertTrue(writer.startWriting()); writer.startSession(atSourceTime: .zero)
        for i in 0..<3 {
            var buffer: CVPixelBuffer?
            CVPixelBufferCreate(kCFAllocatorDefault, 64, 48, kCVPixelFormatType_32BGRA, nil, &buffer)
            let pixel = try XCTUnwrap(buffer)
            CVPixelBufferLockBaseAddress(pixel, [])
            memset(CVPixelBufferGetBaseAddress(pixel)!, Int32(i * 60), CVPixelBufferGetBytesPerRow(pixel) * 48)
            CVPixelBufferUnlockBaseAddress(pixel, [])
            var attempts = 0
            while !input.isReadyForMoreMediaData && attempts < 100 { try await Task.sleep(nanoseconds: 10_000_000); attempts += 1 }
            XCTAssertTrue(adaptor.append(pixel, withPresentationTime: CMTime(seconds: [0.0, 0.033823, 0.068827][i], preferredTimescale: 1_000_000)))
        }
        input.markAsFinished(); await writer.finishWriting()
        XCTAssertEqual(writer.status, .completed, writer.error?.localizedDescription ?? "")
    }
}
