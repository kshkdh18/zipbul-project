import Foundation
import AVFoundation

public enum PackageValidator {
    public static func validate(_ directory: URL, manifest: SessionManifest, checkHashes: Bool = false) async -> ValidationReport {
        var report = ValidationReport()
        let decoder = JSON.decoder()
        var frames: [Int: FrameRecord] = [:]
        var expectedVideo: [Double] = []
        do {
            try Files.forEachLine(directory.appendingPathComponent("frames.jsonl")) { data in
                let frame = try decoder.decode(FrameRecord.self, from: data)
                if frames.updateValue(frame, forKey: frame.frameId) != nil { report.issue("Duplicate frame ID: \(frame.frameId)") }
                guard validMatrix(frame.cameraTransform, n: 4), validMatrix(frame.intrinsics, n: 3), frame.imageWidth > 0, frame.imageHeight > 0, frame.arTimestamp.isFinite else { report.issue("Invalid camera metadata for frame: \(frame.frameId)"); return }
                if let origin = manifest.timeOrigin {
                    report.recordedDuration = max(report.recordedDuration, frame.arTimestamp - origin + 1 / Double(max(1, manifest.settings.videoFps)))
                }
                if !["written", "not_sampled"].contains(frame.videoStatus) { report.videoDroppedCount += 1 }
                if frame.videoStatus == "written" {
                    if let pts = frame.videoPts, let origin = manifest.timeOrigin, abs(pts - (frame.arTimestamp - origin)) <= 0.000_002 {
                        expectedVideo.append(pts)
                    } else { report.issue("Video timestamp mismatch for frame: \(frame.frameId)") }
                } else if frame.videoPts != nil { report.issue("PTS for an unwritten frame: \(frame.frameId)") }
            }
            report.frameCount = frames.count
            if frames.isEmpty { report.issue("No frame records were saved.") }
        } catch { report.issue("Frame validation: \(error.localizedDescription)") }
        do {
            var depthEnd: UInt64 = 0, confidenceEnd: UInt64 = 0
            let depthSize = try Files.size(directory.appendingPathComponent("depth.bin"))
            let confidenceSize = try Files.size(directory.appendingPathComponent("confidence.bin"))
            var ids = Set<Int>()
            try Files.forEachLine(directory.appendingPathComponent("depth-index.jsonl")) { data in
                let record = try decoder.decode(DepthRecord.self, from: data)
                guard ids.insert(record.frameId).inserted, let frame = frames[record.frameId], abs(frame.arTimestamp - record.arTimestamp) < 0.000_001 else { report.issue("Depth frame association mismatch: \(record.frameId)"); return }
                if record.missingReason != nil {
                    report.depthMissingCount += 1
                    if record.depthOffset != nil || record.confidenceOffset != nil { report.issue("A missing depth sample contains a binary reference.") }
                    return
                }
                guard record.width > 0, record.height > 0, record.width <= 16_384, record.height <= 16_384,
                      let offset = record.depthOffset, let length = record.depthLength,
                      let cOffset = record.confidenceOffset, let cLength = record.confidenceLength,
                      length == record.width * record.height * 4, cLength == record.width * record.height,
                      offset == depthEnd, cOffset == confidenceEnd,
                      offset <= depthSize, UInt64(length) <= depthSize - offset,
                      cOffset <= confidenceSize, UInt64(cLength) <= confidenceSize - cOffset else {
                    report.issue("Invalid depth binary range for frame: \(record.frameId)"); return
                }
                let expected = Geometry.scaledIntrinsics(frame.intrinsics, imageWidth: frame.imageWidth, imageHeight: frame.imageHeight, depthWidth: record.width, depthHeight: record.height)
                if record.intrinsics != expected { report.issue("Depth intrinsics mismatch for frame: \(record.frameId)") }
                depthEnd = offset + UInt64(length); confidenceEnd = cOffset + UInt64(cLength)
                report.depthCount += 1
            }
            if depthEnd != depthSize || confidenceEnd != confidenceSize { report.issue("Binary data is missing an index entry.") }
            if report.depthCount == 0 { report.issue("No depth data was saved.") }
        } catch { report.issue("Depth validation: \(error.localizedDescription)") }
        do {
            let mesh = try OBJ.read(directory.appendingPathComponent("mesh.obj"))
            report.meshVertexCount = mesh.vertices.count; report.meshFaceCount = mesh.indices.count / 3
        } catch { report.issue("Mesh validation: \(error.localizedDescription)") }
        do {
            var count = 0
            try Files.forEachLine(directory.appendingPathComponent("events.jsonl")) { data in
                _ = try decoder.decode(CaptureEvent.self, from: data); count += 1
            }
            if count == 0 { report.issue("No capture events were saved.") }
        } catch { report.issue("Event validation: \(error.localizedDescription)") }
        do {
            let asset = AVURLAsset(url: directory.appendingPathComponent("video.mp4"))
            guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw ScanError.invalid("No video track was found.") }
            let size = try await track.load(.naturalSize)
            let transform = try await track.load(.preferredTransform)
            if Int(size.width) != manifest.settings.imageWidth || Int(size.height) != manifest.settings.imageHeight { report.issue("Video dimensions do not match the recording settings.") }
            let actualTransform = [transform.a, transform.b, transform.c, transform.d, transform.tx, transform.ty].map(Double.init)
            if actualTransform != manifest.settings.videoTransform { report.issue("Video orientation does not match the recording settings.") }
            let reader = try AVAssetReader(asset: asset)
            let output = AVAssetReaderTrackOutput(track: track, outputSettings: nil)
            output.alwaysCopiesSampleData = false
            reader.add(output)
            guard reader.startReading() else { throw reader.error ?? ScanError.invalid("Could not read the video") }
            expectedVideo.sort()
            var index = 0
            while let sample = output.copyNextSampleBuffer() {
                // AVAssetReader also emits zero-sample boundary markers, including invalid PTS.
                guard CMSampleBufferGetNumSamples(sample) > 0 else { continue }
                let pts = CMSampleBufferGetPresentationTimeStamp(sample).seconds
                if index >= expectedVideo.count || abs(pts - expectedVideo[index]) > 0.000_01 { report.issue("Video sample PTS mismatch: \(index)") }
                index += 1
            }
            report.videoSampleCount = index
            if reader.status != .completed { report.issue("The video could not be read to the end.") }
            if index == 0 || index != expectedVideo.count { report.issue("The video sample count does not match the frame records.") }
        } catch { report.issue("Video validation: \(error.localizedDescription)") }
        if manifest.summary.videoDropped > 0 || manifest.summary.depthMissing > 0 { report.warnings.append("Some video or depth samples were missed.") }
        if manifest.summary.trackingLimitedFrames > 0 { report.warnings.append("Tracking was unstable during part of the scan.") }
        if checkHashes {
            do {
                if try Files.payloads(directory) != manifest.files { report.issue("File size or SHA-256 mismatch") }
            } catch { report.issue("Checksum verification: \(error.localizedDescription)") }
        }
        return report
    }
    private static func validMatrix(_ rows: [[Float]], n: Int) -> Bool {
        rows.count == n && rows.allSatisfy { $0.count == n && $0.allSatisfy(\.isFinite) }
    }
}
