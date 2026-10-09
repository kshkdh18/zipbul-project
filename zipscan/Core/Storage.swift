import Foundation
import CryptoKit
import ZIPFoundation

public final class JSONLinesWriter {
    private let handle: FileHandle
    private let encoder = JSON.encoder()
    public init(_ url: URL) throws {
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else { throw ScanError.invalid("파일 생성 실패: \(url.lastPathComponent)") }
        handle = try FileHandle(forWritingTo: url)
    }
    public func append<T: Encodable>(_ value: T) throws {
        var data = try encoder.encode(value); data.append(0x0a)
        try handle.write(contentsOf: data)
    }
    public func flush() throws { try handle.synchronize() }
    public func close() throws { try handle.synchronize(); try handle.close() }
    deinit { try? handle.close() }
}

public enum Files {
    public static let required = ["video.mp4", "frames.jsonl", "mesh.obj", "depth.bin", "confidence.bin", "depth-index.jsonl", "events.jsonl", "validation.json"]
    public static func size(_ url: URL) throws -> UInt64 {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        return (attributes[.size] as? NSNumber)?.uint64Value ?? 0
    }
    public static func available(_ url: URL) -> Int64 {
        #if os(iOS)
        if let value = try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]).volumeAvailableCapacityForImportantUsage { return value }
        #endif
        let attributes = try? FileManager.default.attributesOfFileSystem(forPath: url.path)
        return (attributes?[.systemFreeSize] as? NSNumber)?.int64Value ?? 0
    }
    public static func digest(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty { hash.update(data: data) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
    public static func payloads(_ directory: URL) throws -> [PayloadFile] {
        try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.isRegularFileKey])
            .filter { $0.lastPathComponent != "manifest.json" && (try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
            .map { try PayloadFile(name: $0.lastPathComponent, bytes: size($0), sha256: digest($0)) }
    }
    public static func forEachLine(_ url: URL, _ visit: (Data) throws -> Void) throws {
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        var pending = Data()
        while let block = try handle.read(upToCount: 65_536), !block.isEmpty {
            pending.append(block)
            var start = pending.startIndex
            while let newline = pending[start...].firstIndex(of: 10) {
                if newline > start { try visit(Data(pending[start..<newline])) }
                start = pending.index(after: newline)
            }
            if start > pending.startIndex { pending = Data(pending[start...]) }
            guard pending.count < 4_194_304 else { throw ScanError.invalid("비정상적으로 긴 데이터 행") }
        }
        // A missing newline means the last append may have been interrupted; never silently accept it.
        guard pending.isEmpty else { throw ScanError.invalid("완료되지 않은 마지막 행: \(url.lastPathComponent)") }
    }
    public static func packRows(base: UnsafeRawPointer, width: Int, height: Int, bytesPerPixel: Int, bytesPerRow: Int) throws -> Data {
        guard width > 0, height > 0, width <= 16_384, height <= 16_384, bytesPerPixel > 0,
              bytesPerRow >= width * bytesPerPixel else { throw ScanError.invalid("잘못된 픽셀 버퍼 크기") }
        var output = Data(capacity: width * height * bytesPerPixel)
        for row in 0..<height { output.append(base.advanced(by: row * bytesPerRow).assumingMemoryBound(to: UInt8.self), count: width * bytesPerPixel) }
        return output
    }
}

public enum Exporter {
    public static func export(session: URL, destination: URL) throws -> URL {
        let manifest = try JSON.load(SessionManifest.self, from: session.appendingPathComponent("manifest.json"))
        guard [.complete, .partial, .failed].contains(manifest.status) else { throw ScanError.invalid("저장이 끝난 뒤 내보낼 수 있습니다.") }
        guard UUID(uuidString: manifest.sessionId) != nil else { throw ScanError.invalid("잘못된 세션 ID") }
        let actual = try Files.payloads(session)
        guard actual == manifest.files else { throw ScanError.invalid("파일이 변경되었습니다. 결과를 다시 검증해 주세요.") }
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        let bytes = actual.reduce(UInt64(0)) { $0 + $1.bytes }
        guard Files.available(destination) > Int64(bytes) + 268_435_456 else { throw ScanError.invalid("ZIP을 만들 저장 공간이 부족합니다. 원본은 보존되어 있습니다.") }
        let output = destination.appendingPathComponent(manifest.exportFileName)
        let temporary = destination.appendingPathComponent(".\(manifest.sessionId)-\(UUID().uuidString).zip")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let archive = try Archive(url: temporary, accessMode: .create)
        let names = ["manifest.json"] + actual.map(\.name)
        for name in names {
            // MP4 is already compressed. Streaming ZIP avoids loading recordings into memory.
            try archive.addEntry(with: name, relativeTo: session, compressionMethod: name == "video.mp4" ? .none : .deflate)
        }
        let reader = try Archive(url: temporary, accessMode: .read)
        guard Set(reader.map(\.path)) == Set(names) else { throw ScanError.invalid("ZIP 파일 목록 검증 실패") }
        for entry in reader {
            var hash = SHA256()
            let crc = try reader.extract(entry, consumer: { hash.update(data: $0) })
            guard crc == entry.checksum else { throw ScanError.invalid("ZIP CRC 검증 실패: \(entry.path)") }
            let expected = entry.path == "manifest.json" ? try Files.digest(session.appendingPathComponent(entry.path)) : actual.first { $0.name == entry.path }!.sha256
            let digest = hash.finalize().map { String(format: "%02x", $0) }.joined()
            guard digest == expected else { throw ScanError.invalid("ZIP 체크섬 검증 실패: \(entry.path)") }
        }
        if FileManager.default.fileExists(atPath: output.path) {
            _ = try FileManager.default.replaceItemAt(output, withItemAt: temporary)
        } else { try FileManager.default.moveItem(at: temporary, to: output) }
        return output
    }
}
