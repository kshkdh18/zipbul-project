import Foundation
import simd

public enum JSON {
    public static func encoder(pretty: Bool = false) -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = pretty ? [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes] : [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }
    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
    public static func save<T: Encodable>(_ value: T, to url: URL) throws {
        try encoder(pretty: true).encode(value).write(to: url, options: .atomic)
    }
    public static func load<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        try decoder().decode(type, from: Data(contentsOf: url))
    }
}

public struct CaptureSettings: Codable, Equatable {
    public var videoFps = 30
    public var depthHz = 10
    public var videoBitrate = 8_000_000
    public var maxDuration: Double = 600
    public var imageWidth = 0
    public var imageHeight = 0
    public var arFps = 0
    public var orientation = "landscapeRight"
    public var videoTransform: [Double] = [1, 0, 0, 1, 0, 0]
    public init() {}
}

public enum SessionStatus: String, Codable {
    case recording, finalizing, complete, partial, failed
    public var title: String {
        switch self {
        case .recording: return "수집 중"
        case .finalizing: return "저장 중"
        case .complete: return "완료"
        case .partial: return "일부 저장"
        case .failed: return "저장 실패"
        }
    }
}

public struct CaptureSummary: Codable {
    public var arFrames = 0
    public var videoExpected = 0
    public var videoWritten = 0
    public var videoDropped = 0
    public var depthExpected = 0
    public var depthWritten = 0
    public var depthMissing = 0
    public var trackingLimitedFrames = 0
    public var meshVertices = 0
    public var meshFaces = 0
    public var duration: Double = 0
    public init() {}
}

public struct PayloadFile: Codable, Equatable {
    public let name: String
    public let bytes: UInt64
    public let sha256: String
    public init(name: String, bytes: UInt64, sha256: String) {
        self.name = name; self.bytes = bytes; self.sha256 = sha256
    }
}

public struct SessionManifest: Codable, Identifiable {
    public var id: String { sessionId }
    public var exportFileName: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Asia/Seoul")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        return formatter.string(from: startedAt) + "_" + sessionId + ".zip"
    }
    public var formatVersion = "1.0"
    public var sessionId: String
    public var startedAt: Date
    public var endedAt: Date?
    public var device: String
    public var osVersion: String
    public var appVersion: String
    public var status: SessionStatus = .recording
    public var settings: CaptureSettings
    public var timeOrigin: Double?
    public var stopReason: String?
    public var summary = CaptureSummary()
    public var warnings: [String] = []
    public var errors: [String] = []
    public var files: [PayloadFile] = []
    public var missingFiles: [String] = []
    public var coordinates = "ARKit right-handed, meters, gravity +Y; camera-to-world; matrices are row arrays; camera forward -Z"
    public var pixels = "sensor-native, top-left pixel center (0,0), +x right +y down; depth is optical-axis meters; no physical image rotation or crop"
    public var depthConvention = "Float32 LE, tightly packed rows; confidence UInt8: 0 low, 1 medium, 2 high; NaN/nonpositive depth invalid; timestamp is ARFrame.timestamp"
    public init(id: String = UUID().uuidString.lowercased(), device: String, osVersion: String, appVersion: String, settings: CaptureSettings = .init()) {
        sessionId = id; startedAt = Date(); self.device = device
        self.osVersion = osVersion; self.appVersion = appVersion; self.settings = settings
    }
}

public struct FrameRecord: Codable {
    public var frameId: Int
    public var arTimestamp: Double
    public var videoPts: Double?
    public var videoStatus: String
    public var cameraTransform: [[Float]]
    public var intrinsics: [[Float]]
    public var imageWidth: Int
    public var imageHeight: Int
    public var trackingState: String
    public var trackingReason: String?
    public var displayTransform: [Double]
    public var displayViewport: [Double]?
    public init(frameId: Int, arTimestamp: Double, cameraTransform: [[Float]], intrinsics: [[Float]], imageWidth: Int, imageHeight: Int, trackingState: String, trackingReason: String?, displayTransform: [Double], displayViewport: [Double]? = nil) {
        self.frameId = frameId; self.arTimestamp = arTimestamp; self.cameraTransform = cameraTransform
        self.intrinsics = intrinsics; self.imageWidth = imageWidth; self.imageHeight = imageHeight
        self.trackingState = trackingState; self.trackingReason = trackingReason
        self.displayTransform = displayTransform; self.displayViewport = displayViewport; videoStatus = "not_sampled"
    }
}

public struct DepthRecord: Codable {
    public var frameId: Int
    public var arTimestamp: Double
    public var width: Int
    public var height: Int
    public var depthOffset: UInt64?
    public var depthLength: Int?
    public var confidenceOffset: UInt64?
    public var confidenceLength: Int?
    public var intrinsics: [[Float]]?
    public var missingReason: String?
    public init(frameId: Int, arTimestamp: Double, width: Int = 0, height: Int = 0, missingReason: String? = nil) {
        self.frameId = frameId; self.arTimestamp = arTimestamp; self.width = width; self.height = height; self.missingReason = missingReason
    }
}

public struct CaptureEvent: Codable {
    public var type: String
    public var arTimestamp: Double?
    public var frameId: Int?
    public var message: String
    public var count: Int?
    public var wallTime = Date()
    public init(_ type: String, message: String, timestamp: Double? = nil, frameId: Int? = nil, count: Int? = nil) {
        self.type = type; self.message = message; arTimestamp = timestamp; self.frameId = frameId; self.count = count
    }
}

public struct ValidationReport: Codable {
    public var checkedAt = Date()
    public var issues: [String] = []
    public var warnings: [String] = []
    public var frameCount = 0
    public var videoSampleCount = 0
    public var videoDroppedCount = 0
    public var depthMissingCount = 0
    public var recordedDuration: Double = 0
    public var depthCount = 0
    public var meshVertexCount = 0
    public var meshFaceCount = 0
    public var passed: Bool { issues.isEmpty }
    public init() {}
    public mutating func issue(_ text: String) {
        if issues.count < 50 { issues.append(text) }
    }
}

public enum ScanError: LocalizedError {
    case invalid(String)
    public var errorDescription: String? { if case let .invalid(message) = self { return message }; return nil }
}

public enum Geometry {
    public static func rows(_ matrix: simd_float4x4) -> [[Float]] {
        (0..<4).map { r in (0..<4).map { c in matrix[c][r] } }
    }
    public static func rows(_ matrix: simd_float3x3) -> [[Float]] {
        (0..<3).map { r in (0..<3).map { c in matrix[c][r] } }
    }
    public static func scaledIntrinsics(_ k: [[Float]], imageWidth: Int, imageHeight: Int, depthWidth: Int, depthHeight: Int) -> [[Float]] {
        let sx = Float(depthWidth) / Float(imageWidth), sy = Float(depthHeight) / Float(imageHeight)
        return [k[0].map { $0 * sx }, k[1].map { $0 * sy }, k[2]]
    }
}

public struct RateSampler {
    private var next: Double?
    private let interval: Double
    public init(hz: Int) { interval = 1 / Double(max(1, hz)) }
    public mutating func take(_ timestamp: Double) -> Bool {
        guard let deadline = next else { next = timestamp + interval; return true }
        guard timestamp + 0.000_1 >= deadline else { return false }
        next = deadline + max(1, floor((timestamp + 0.000_1 - deadline) / interval) + 1) * interval
        return true
    }
}
