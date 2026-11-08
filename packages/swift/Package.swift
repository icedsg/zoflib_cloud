// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "ZoflibCloud",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "ZoflibCloud", targets: ["ZoflibCloud"])],
    targets: [
        .target(name: "ZoflibCloud"),
        .executableTarget(name: "ZoflibCloudDriver", dependencies: ["ZoflibCloud"]),
        .testTarget(name: "ZoflibCloudTests", dependencies: ["ZoflibCloud"]),
    ]
)
