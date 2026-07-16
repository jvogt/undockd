// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Dockd",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "Dockd",
            path: "Sources/Dockd"
        )
    ]
)
