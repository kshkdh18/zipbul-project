// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ZipscanCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "ZipscanCore", targets: ["ZipscanCore"]), .executable(name: "zipscan-validate", targets: ["ZipscanValidate"])],
    dependencies: [.package(url: "https://github.com/weichsel/ZIPFoundation.git", exact: "0.9.20")],
    targets: [
        .target(name: "ZipscanCore", dependencies: ["ZIPFoundation"], path: "Core"),
        .executableTarget(name: "ZipscanValidate", dependencies: ["ZipscanCore"], path: "Tools/ZipscanValidate"),
        .testTarget(name: "ZipscanCoreTests", dependencies: ["ZipscanCore"], path: "Tests")
    ]
)
