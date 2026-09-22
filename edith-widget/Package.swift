// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "EdithWidget",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(
            name: "EdithWidget",
            path: "Sources/EdithWidget"
        )
    ]
)
