import SwiftUI
import ZipscanCore

struct StoredSession: Identifiable {
    var id: String { directory.lastPathComponent }
    let directory: URL
    var manifest: SessionManifest
}

@MainActor final class SessionLibrary: ObservableObject {
    @Published var sessions: [StoredSession] = []
    @Published var loading = false
    @Published var error: String?
    let root: URL
    let exports: URL
    init() {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        root = documents.appendingPathComponent("Sessions", isDirectory: true)
        exports = documents.appendingPathComponent("Exports", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: exports, withIntermediateDirectories: true)
        } catch { self.error = error.localizedDescription }
    }
    func refresh() async {
        loading = true
        let root = root
        let result = await Task.detached(priority: .utility) { () -> ([StoredSession], [String]) in
            var sessions: [StoredSession] = [], errors: [String] = []
            do {
                let folders = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey])
                for directory in folders where (try? directory.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                    do {
                        let url = directory.appendingPathComponent("manifest.json")
                        var manifest = try JSON.load(SessionManifest.self, from: url)
                        if manifest.status == .recording || manifest.status == .finalizing {
                            manifest = try await SessionRecovery.recover(directory)
                        }
                        sessions.append(StoredSession(directory: directory, manifest: manifest))
                    } catch { errors.append("\(directory.lastPathComponent): \(error.localizedDescription)") }
                }
            } catch { errors.append(error.localizedDescription) }
            return (sessions.sorted { $0.manifest.startedAt > $1.manifest.startedAt }, errors)
        }.value
        sessions = result.0; error = result.1.isEmpty ? nil : result.1.joined(separator: "\n")
        loading = false
    }
    func delete(_ session: StoredSession) async {
        guard session.directory.deletingLastPathComponent().standardizedFileURL == root.standardizedFileURL, UUID(uuidString: session.id) != nil else { error = "세션 경로가 올바르지 않습니다."; return }
        let directory = session.directory, export = exports.appendingPathComponent(session.manifest.exportFileName)
        do {
            try await Task.detached(priority: .utility) {
                if FileManager.default.fileExists(atPath: export.path) { try FileManager.default.removeItem(at: export) }
                try FileManager.default.removeItem(at: directory)
            }.value
            sessions.removeAll { $0.id == session.id }
        } catch { self.error = error.localizedDescription }
    }
}
