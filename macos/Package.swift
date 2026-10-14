// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "MisNotas",
    defaultLocalization: "es",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "MisNotas", targets: ["MisNotas"]),
    ],
    dependencies: [
        .package(url: "https://github.com/groue/GRDB.swift.git", from: "7.0.0"),
    ],
    targets: [
        // Lógica sin UI (modelos, base de datos, sincronización, importación): testeable con `swift test`.
        .target(
            name: "MisNotasCore",
            dependencies: [.product(name: "GRDB", package: "GRDB.swift")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "MisNotas",
            dependencies: ["MisNotasCore"],
            // Las fuentes las copia scripts/build-app.sh a Contents/Resources (ver Theme.registerFonts).
            exclude: ["Resources"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "MisNotasTests",
            dependencies: ["MisNotasCore"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
