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
                if frames.updateValue(frame, forKey: frame.frameId) != nil { report.issue("중복 frame_id: \(frame.frameId)") }
                guard validMatrix(frame.cameraTransform, n: 4), validMatrix(frame.intrinsics, n: 3), frame.imageWidth > 0, frame.imageHeight > 0, frame.arTimestamp.isFinite else { report.issue("프레임 카메라 정보 오류: \(frame.frameId)"); return }
                if let origin = manifest.timeOrigin {
                    report.recordedDuration = max(report.recordedDuration, frame.arTimestamp - origin + 1 / Double(max(1, manifest.settings.videoFps)))
                }
                if !["written", "not_sampled"].contains(frame.videoStatus) { report.videoDroppedCount += 1 }
                if frame.videoStatus == "written" {
                    if let pts = frame.videoPts, let origin = manifest.timeOrigin, abs(pts - (frame.arTimestamp - origin)) <= 0.000_002 {
                        expectedVideo.append(pts)
                    } else { report.issue("영상 시간 대응 오류: \(frame.frameId)") }
                } else if frame.videoPts != nil { report.issue("저장되지 않은 프레임의 PTS: \(frame.frameId)") }
            }
            report.frameCount = frames.count
            if frames.isEmpty { report.issue("프레임 기록이 없습니다.") }
        } catch { report.issue("프레임 검증: \(error.localizedDescription)") }
        do {
            var depthEnd: UInt64 = 0, confidenceEnd: UInt64 = 0
            let depthSize = try Files.size(directory.appendingPathComponent("depth.bin"))
            let confidenceSize = try Files.size(directory.appendingPathComponent("confidence.bin"))
            var ids = Set<Int>()
            try Files.forEachLine(directory.appendingPathComponent("depth-index.jsonl")) { data in
                let record = try decoder.decode(DepthRecord.self, from: data)
                guard ids.insert(record.frameId).inserted, let frame = frames[record.frameId], abs(frame.arTimestamp - record.arTimestamp) < 0.000_001 else { report.issue("깊이 프레임 연결 오류: \(record.frameId)"); return }
                if record.missingReason != nil {
                    report.depthMissingCount += 1
                    if record.depthOffset != nil || record.confidenceOffset != nil { report.issue("누락 깊이에 바이너리 참조가 있습니다.") }
                    return
                }
                guard record.width > 0, record.height > 0, record.width <= 16_384, record.height <= 16_384,
                      let offset = record.depthOffset, let length = record.depthLength,
                      let cOffset = record.confidenceOffset, let cLength = record.confidenceLength,
                      length == record.width * record.height * 4, cLength == record.width * record.height,
                      offset == depthEnd, cOffset == confidenceEnd,
                      offset <= depthSize, UInt64(length) <= depthSize - offset,
                      cOffset <= confidenceSize, UInt64(cLength) <= confidenceSize - cOffset else {
                    report.issue("깊이 바이너리 범위 오류: \(record.frameId)"); return
                }
                let expected = Geometry.scaledIntrinsics(frame.intrinsics, imageWidth: frame.imageWidth, imageHeight: frame.imageHeight, depthWidth: record.width, depthHeight: record.height)
                if record.intrinsics != expected { report.issue("깊이 내부 파라미터 오류: \(record.frameId)") }
                depthEnd = offset + UInt64(length); confidenceEnd = cOffset + UInt64(cLength)
                report.depthCount += 1
            }
            if depthEnd != depthSize || confidenceEnd != confidenceSize { report.issue("인덱스가 없는 바이너리 데이터가 있습니다.") }
            if report.depthCount == 0 { report.issue("저장된 깊이 데이터가 없습니다.") }
        } catch { report.issue("깊이 검증: \(error.localizedDescription)") }
        do {
            let mesh = try OBJ.read(directory.appendingPathComponent("mesh.obj"))
            report.meshVertexCount = mesh.vertices.count; report.meshFaceCount = mesh.indices.count / 3
        } catch { report.issue("메쉬 검증: \(error.localizedDescription)") }
        do {
            var count = 0
            try Files.forEachLine(directory.appendingPathComponent("events.jsonl")) { data in
                _ = try decoder.decode(CaptureEvent.self, from: data); count += 1
            }
            if count == 0 { report.issue("수집 이벤트 기록이 없습니다.") }
        } catch { report.issue("이벤트 검증: \(error.localizedDescription)") }
        do {
            let asset = AVURLAsset(url: directory.appendingPathComponent("video.mp4"))
            guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw ScanError.invalid("영상 트랙이 없습니다.") }
            let size = try await track.load(.naturalSize)
            let transform = try await track.load(.preferredTransform)
            if Int(size.width) != manifest.settings.imageWidth || Int(size.height) != manifest.settings.imageHeight { report.issue("영상 해상도가 설정과 다릅니다.") }
            let actualTransform = [transform.a, transform.b, transform.c, transform.d, transform.tx, transform.ty].map(Double.init)
            if actualTransform != manifest.settings.videoTransform { report.issue("영상 회전 정보가 설정과 다릅니다.") }
            let reader = try AVAssetReader(asset: asset)
            let output = AVAssetReaderTrackOutput(track: track, outputSettings: nil)
            output.alwaysCopiesSampleData = false
            reader.add(output)
            guard reader.startReading() else { throw reader.error ?? ScanError.invalid("영상 읽기 실패") }
            expectedVideo.sort()
            var index = 0
            while let sample = output.copyNextSampleBuffer() {
                // AVAssetReader also emits zero-sample boundary markers, including invalid PTS.
                guard CMSampleBufferGetNumSamples(sample) > 0 else { continue }
                let pts = CMSampleBufferGetPresentationTimeStamp(sample).seconds
                if index >= expectedVideo.count || abs(pts - expectedVideo[index]) > 0.000_01 { report.issue("영상 샘플 PTS 불일치: \(index)") }
                index += 1
            }
            report.videoSampleCount = index
            if reader.status != .completed { report.issue("영상이 끝까지 읽히지 않습니다.") }
            if index == 0 || index != expectedVideo.count { report.issue("영상 샘플 수와 프레임 기록이 다릅니다.") }
        } catch { report.issue("영상 검증: \(error.localizedDescription)") }
        if manifest.summary.videoDropped > 0 || manifest.summary.depthMissing > 0 { report.warnings.append("일부 수집 샘플이 누락되었습니다.") }
        if manifest.summary.trackingLimitedFrames > 0 { report.warnings.append("추적이 불안정했던 구간이 있습니다.") }
        if checkHashes {
            do {
                if try Files.payloads(directory) != manifest.files { report.issue("파일 크기 또는 SHA-256 불일치") }
            } catch { report.issue("체크섬 검증: \(error.localizedDescription)") }
        }
        return report
    }
    private static func validMatrix(_ rows: [[Float]], n: Int) -> Bool {
        rows.count == n && rows.allSatisfy { $0.count == n && $0.allSatisfy(\.isFinite) }
    }
}
