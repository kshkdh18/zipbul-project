import XCTest
import AVFoundation
import simd
import ZipscanCore
@testable import Zipscan

final class RecorderTests: XCTestCase {
    private var directory: URL!
    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("recorder-test-" + UUID().uuidString)
    }
    override func tearDownWithError() throws {
        if FileManager.default.fileExists(atPath: directory.path) { try FileManager.default.removeItem(at: directory) }
    }
    func testCompleteRecordingAndDuplicateFinish() async throws {
        let result = try await record(missingFirstDepth: false)
        XCTAssertEqual(result.status, .complete, result.errors.joined(separator: "; "))
        XCTAssertEqual(result.summary.videoWritten, 6)
        XCTAssertEqual(result.summary.depthWritten, 2)
        let checked = await PackageValidator.validate(directory, manifest: result, checkHashes: true)
        XCTAssertTrue(checked.passed, checked.issues.joined(separator: "; "))
    }
    func testMissingDepthRemainsPartialWithPlayableVideo() async throws {
        let result = try await record(missingFirstDepth: true)
        XCTAssertEqual(result.status, .partial)
        XCTAssertEqual(result.summary.depthMissing, 1)
        XCTAssertEqual(result.summary.videoWritten, 6)
        XCTAssertEqual(result.summary.depthWritten, 1)
        let checked = await PackageValidator.validate(directory, manifest: result, checkHashes: true)
        XCTAssertTrue(checked.passed, checked.issues.joined(separator: "; "))
        XCTAssertFalse(checked.warnings.isEmpty)
    }
    func testStorageFailureReturnsFailureAndKeepsErrorEvidence() async throws {
        let sink = try Recorder(directory: directory, manifest: manifest())
        try FileManager.default.removeItem(at: directory)
        let packet = try makePacket(id: 1, missingDepth: false, sink: sink)
        sink.submit(packet)
        let result = await finish(sink)
        XCTAssertEqual(result.status, .failed)
        XCTAssertFalse(result.errors.isEmpty)
    }
    private func manifest() -> SessionManifest {
        var manifest = SessionManifest(device: "unit-test", osVersion: "test", appVersion: "0.1.0")
        manifest.settings.imageWidth = 64; manifest.settings.imageHeight = 48; manifest.settings.arFps = 30
        return manifest
    }
    private func record(missingFirstDepth: Bool) async throws -> SessionManifest {
        let sink = try Recorder(directory: directory, manifest: manifest())
        for id in 1...6 {
            sink.submit(try makePacket(id: id, missingDepth: id == 1 && missingFirstDepth, sink: sink))
            try await Task.sleep(nanoseconds: 80_000_000)
        }
        let result = await finish(sink)
        let duplicate = expectation(description: "Repeated finish must not close files again")
        duplicate.isInverted = true
        sink.finish(meshes: [], reason: "user", arFrames: 0, limitedFrames: 0, duration: 0) { _ in duplicate.fulfill() }
        await fulfillment(of: [duplicate], timeout: 0.15)
        return result
    }
    private func finish(_ sink: Recorder) async -> SessionManifest {
        await withCheckedContinuation { continuation in
            let mesh = MeshChunk(vertices: [SIMD3(0, 0, 0), SIMD3(1, 0, 0), SIMD3(0, 1, 0)], indices: [0, 1, 2])
            sink.finish(meshes: [mesh], reason: "user", arFrames: 6, limitedFrames: 0, duration: 0.2) { continuation.resume(returning: $0) }
        }
    }
    private func makePacket(id: Int, missingDepth: Bool, sink: Recorder) throws -> CapturePacket {
        XCTAssertTrue(sink.reserveImageSlot())
        var buffer: CVPixelBuffer?
        CVPixelBufferCreate(kCFAllocatorDefault, 64, 48, kCVPixelFormatType_32BGRA, nil, &buffer)
        let pixel = try XCTUnwrap(buffer)
        CVPixelBufferLockBaseAddress(pixel, [])
        memset(CVPixelBufferGetBaseAddress(pixel)!, 80, CVPixelBufferGetBytesPerRow(pixel) * 48)
        CVPixelBufferUnlockBaseAddress(pixel, [])
        let wantsDepth = id == 1 || id == 4
        let raw: [Float] = [1, 2, 3, 4]
        let depth = CapturedDepth(width: 2, height: 2, depth: raw.withUnsafeBufferPointer { Data(buffer: $0) }, confidence: Data([2, 2, 2, 2]))
        let record = FrameRecord(frameId: id, arTimestamp: 1000 + Double(id - 1) / 30, cameraTransform: Geometry.rows(matrix_identity_float4x4), intrinsics: [[100, 0, 32], [0, 100, 24], [0, 0, 1]], imageWidth: 64, imageHeight: 48, trackingState: "normal", trackingReason: nil, displayTransform: [1, 0, 0, 1, 0, 0])
        return CapturePacket(record: record, wantsVideo: true, wantsDepth: wantsDepth, image: pixel, depth: wantsDepth && !missingDepth ? depth : nil, depthError: missingDepth ? "scene_depth_or_confidence_unavailable" : nil, ownsImageSlot: true)
    }
}
