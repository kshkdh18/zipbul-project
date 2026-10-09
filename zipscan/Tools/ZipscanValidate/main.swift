import Foundation
import ZipscanCore

@main struct Validate {
    static func main() async {
        guard CommandLine.arguments.count == 2 else {
            FileHandle.standardError.write(Data("Usage: swift run zipscan-validate <extracted-session-directory>\n".utf8)); exit(2)
        }
        do {
            let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            let manifest = try JSON.load(SessionManifest.self, from: directory.appendingPathComponent("manifest.json"))
            let report = await PackageValidator.validate(directory, manifest: manifest, checkHashes: true)
            var data = try JSON.encoder(pretty: true).encode(report); data.append(10)
            FileHandle.standardOutput.write(data)
            exit(report.passed ? 0 : 1)
        } catch { FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(2) }
    }
}
