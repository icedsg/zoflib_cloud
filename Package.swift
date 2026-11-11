// swift-tools-version:5.10
// Root manifest so Swift Package Manager can add this repository by its git URL. The sources live in packages/swift,
// which keeps its own Package.swift for working inside that folder; keep the two manifests in step.
import PackageDescription

let package = Package(
    name: "ZoflibCloud",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "ZoflibCloud", targets: ["ZoflibCloud"])],
    targets: [
        .target(name: "ZoflibCloud", path: "packages/swift/Sources/ZoflibCloud"),
        .executableTarget(name: "ZoflibCloudDriver", dependencies: ["ZoflibCloud"],
                          path: "packages/swift/Sources/ZoflibCloudDriver"),
        .testTarget(name: "ZoflibCloudTests", dependencies: ["ZoflibCloud"],
                    path: "packages/swift/Tests/ZoflibCloudTests"),
    ]
)
