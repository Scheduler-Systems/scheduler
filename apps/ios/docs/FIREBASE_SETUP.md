# Firebase Configuration

This app requires Firebase configuration files to run.

## Setup

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create or select your project
3. Add an iOS app with bundle ID: `com.example.scheduler`
4. Download `GoogleService-Info.plist`
5. Place it in `Sources/SchedulerApp/Resources/`

## Required Firebase Services

- **Authentication**: Email/Password, Google, Apple, Phone
- Enable these providers in Firebase Console > Authentication > Sign-in method

## Google Sign-In Setup

1. Add the reversed client ID from `GoogleService-Info.plist` to your `Info.plist`:
```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleTypeRole</key>
        <string>Editor</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>YOUR_REVERSED_CLIENT_ID</string>
        </array>
    </dict>
</array>
```

2. Add URL scheme to `Info.plist`:
```xml
<key>LSApplicationQueriesSchemes</key>
<array>
    <string>google</string>
</array>
```

## Apple Sign-In Setup

1. Enable Apple Sign-In in Firebase Console
2. Configure Sign in with Apple in your Apple Developer account
3. Add the Sign in with Apple capability in Xcode

## Building

```bash
swift build
```

Or open in Xcode:
```bash
open Package.swift
```
