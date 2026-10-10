import Foundation
import simd

public struct MeshChunk {
    public var vertices: [SIMD3<Float>]
    public var indices: [UInt32]
    public init(vertices: [SIMD3<Float>], indices: [UInt32]) { self.vertices = vertices; self.indices = indices }
    public init(vertices: [SIMD3<Float>], indices: [UInt32], transform: simd_float4x4) {
        self.vertices = vertices.map { let v = transform * SIMD4($0.x, $0.y, $0.z, 1); return SIMD3(v.x, v.y, v.z) }
        self.indices = indices
    }
}

public enum OBJ {
    public static func write(_ chunks: [MeshChunk], to url: URL) throws -> (vertices: Int, faces: Int) {
        guard FileManager.default.createFile(atPath: url.path, contents: nil) else { throw ScanError.invalid("Could not create the mesh file") }
        let handle = try FileHandle(forWritingTo: url); defer { try? handle.close() }
        try handle.write(contentsOf: Data("# Zipscan 1.0; meters; ARKit world coordinates\n".utf8))
        var base: UInt32 = 1, faces = 0
        for chunk in chunks {
            guard chunk.indices.count % 3 == 0, chunk.indices.allSatisfy({ Int($0) < chunk.vertices.count }), chunk.vertices.allSatisfy({ $0.x.isFinite && $0.y.isFinite && $0.z.isFinite }) else { throw ScanError.invalid("Invalid mesh coordinates or indices.") }
            var text = ""
            for v in chunk.vertices {
                text += "v \(v.x) \(v.y) \(v.z)\n"
                if text.utf8.count > 65_536 { try handle.write(contentsOf: Data(text.utf8)); text.removeAll(keepingCapacity: true) }
            }
            for i in stride(from: 0, to: chunk.indices.count, by: 3) {
                text += "f \(chunk.indices[i] + base) \(chunk.indices[i+1] + base) \(chunk.indices[i+2] + base)\n"
                if text.utf8.count > 65_536 { try handle.write(contentsOf: Data(text.utf8)); text.removeAll(keepingCapacity: true) }
            }
            try handle.write(contentsOf: Data(text.utf8)); base += UInt32(chunk.vertices.count); faces += chunk.indices.count / 3
        }
        try handle.synchronize()
        return (Int(base) - 1, faces)
    }
    public static func read(_ url: URL) throws -> MeshChunk {
        var vertices: [SIMD3<Float>] = [], indices: [UInt32] = []
        try Files.forEachLine(url) { data in
            guard let line = String(data: data, encoding: .utf8) else { throw ScanError.invalid("Invalid UTF-8 in mesh file") }
            let parts = line.split(whereSeparator: \.isWhitespace)
            guard let kind = parts.first else { return }
            if kind == "v" {
                guard parts.count == 4, let x = Float(parts[1]), let y = Float(parts[2]), let z = Float(parts[3]), x.isFinite, y.isFinite, z.isFinite else { throw ScanError.invalid("Invalid mesh vertex") }
                vertices.append(SIMD3(x, y, z))
            } else if kind == "f" {
                guard parts.count == 4 else { throw ScanError.invalid("Mesh contains a non-triangular face") }
                for item in parts.dropFirst() {
                    guard let index = UInt32(item), index > 0 else { throw ScanError.invalid("Invalid mesh face index") }
                    indices.append(index - 1)
                }
            }
        }
        guard !vertices.isEmpty, !indices.isEmpty, indices.allSatisfy({ Int($0) < vertices.count }) else { throw ScanError.invalid("The mesh is empty or contains invalid face indices.") }
        return MeshChunk(vertices: vertices, indices: indices)
    }
}
