// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SchedulerApp",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .executable(name: "SchedulerApp", targets: ["SchedulerApp"])
    ],
    dependencies: [
        .package(url: "https://github.com/firebase/firebase-ios-sdk.git", from: "11.0.0"),
        .package(url: "https://github.com/google/GoogleSignIn-iOS.git", from: "8.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "SchedulerApp",
            dependencies: [
                .product(name: "FirebaseAuth", package: "firebase-ios-sdk"),
                .product(name: "FirebaseCore", package: "firebase-ios-sdk"),
                .product(name: "FirebaseFirestore", package: "firebase-ios-sdk"),
                .product(name: "GoogleSignIn", package: "GoogleSignIn-iOS"),
                .product(name: "GoogleSignInSwift", package: "GoogleSignIn-iOS"),
            ],
            path: "Sources/SchedulerApp",
            resources: [.process("Resources")]
        ),
        .testTarget(
            name: "SchedulerAppTests",
            dependencies: ["SchedulerApp"],
            path: "Tests/SchedulerAppTests"
        ),
    ]
)
