import Foundation

public enum SessionRecovery {
    /// Recovers readable evidence without claiming that an interrupted recording completed.
    public static func recover(_ directory: URL) async throws -> SessionManifest {
        let url = directory.appendingPathComponent("manifest.json")
        var manifest = try JSON.load(SessionManifest.self, from: url)
        guard manifest.status == .recording || manifest.status == .finalizing else { return manifest }
        let report = await PackageValidator.validate(directory, manifest: manifest)
        manifest.status = .partial; manifest.stopReason = "recovered_after_interruption"
        manifest.errors = Array(Set(manifest.errors + report.issues)).sorted()
        manifest.warnings = report.warnings + ["Recovered readable data from an interrupted scan. The video or final mesh may be missing."]
        manifest.summary.duration = max(manifest.summary.duration, report.recordedDuration)
        manifest.summary.videoWritten = report.videoSampleCount
        manifest.summary.depthWritten = report.depthCount
        manifest.summary.videoDropped = max(manifest.summary.videoDropped, report.videoDroppedCount)
        manifest.summary.depthMissing = max(manifest.summary.depthMissing, report.depthMissingCount)
        manifest.summary.videoExpected = max(manifest.summary.videoExpected, report.videoSampleCount + report.videoDroppedCount)
        manifest.summary.depthExpected = max(manifest.summary.depthExpected, report.depthCount + report.depthMissingCount)
        manifest.summary.meshVertices = report.meshVertexCount; manifest.summary.meshFaces = report.meshFaceCount
        if report.videoSampleCount == 0 && report.depthCount == 0 && report.meshFaceCount == 0 { manifest.status = .failed }
        try JSON.save(report, to: directory.appendingPathComponent("validation.json"))
        manifest.files = try Files.payloads(directory)
        manifest.missingFiles = Files.required.filter { name in !manifest.files.contains { $0.name == name } }
        try JSON.save(manifest, to: url)
        return manifest
    }
}
