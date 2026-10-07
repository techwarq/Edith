import AppKit
import AVFoundation
import ApplicationServices
import CoreGraphics
import Speech

enum Permission: String, CaseIterable, Identifiable {
    case microphone, speech, inputMonitoring, accessibility, screenRecording

    var id: String { rawValue }

    var title: String {
        switch self {
        case .microphone: return "Microphone"
        case .speech: return "Speech Recognition"
        case .inputMonitoring: return "Input Monitoring"
        case .accessibility: return "Accessibility"
        case .screenRecording: return "Screen Recording"
        }
    }

    var purpose: String {
        switch self {
        case .microphone: return "hear you"
        case .speech: return "transcribe as you talk"
        case .inputMonitoring: return "the ⌃ / ⌃⌘ shortcuts"
        case .accessibility: return "click & type in other apps"
        case .screenRecording: return "take screenshots"
        }
    }

    var symbol: String {
        switch self {
        case .microphone: return "mic.fill"
        case .speech: return "waveform"
        case .inputMonitoring: return "keyboard"
        case .accessibility: return "cursorarrow.click.2"
        case .screenRecording: return "camera.viewfinder"
        }
    }

    var needsRelaunchAfterGrant: Bool { self == .screenRecording }

    private var settingsAnchor: String {
        switch self {
        case .microphone: return "Privacy_Microphone"
        case .speech: return "Privacy_SpeechRecognition"
        case .inputMonitoring: return "Privacy_ListenEvent"
        case .accessibility: return "Privacy_Accessibility"
        case .screenRecording: return "Privacy_ScreenCapture"
        }
    }

    var isGranted: Bool {
        switch self {
        case .microphone: return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        case .speech: return SFSpeechRecognizer.authorizationStatus() == .authorized
        case .inputMonitoring: return CGPreflightListenEventAccess()
        case .accessibility: return AXIsProcessTrusted()
        case .screenRecording: return CGPreflightScreenCaptureAccess()
        }
    }

    func openSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(settingsAnchor)")!
        NSWorkspace.shared.open(url)
    }
}

@MainActor
final class PermissionsManager: ObservableObject {
    @Published private(set) var granted: [Permission: Bool] = [:]

    private var pollTimer: Timer?

    init() { refresh() }

    var missing: [Permission] { Permission.allCases.filter { granted[$0] != true } }
    var allGranted: Bool { missing.isEmpty }

    func refresh() {
        var next: [Permission: Bool] = [:]
        for permission in Permission.allCases { next[permission] = permission.isGranted }
        if next != granted { granted = next }
    }

    func request(_ permission: Permission) {
        switch permission {
        case .microphone:
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
                AVCaptureDevice.requestAccess(for: .audio) { _ in
                    Task { @MainActor [weak self] in self?.refresh() }
                }
            } else {
                permission.openSettings()
            }
        case .speech:
            if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
                Self.requestSpeech { [weak self] in self?.refresh() }
            } else {
                permission.openSettings()
            }
        case .inputMonitoring:
            if !CGRequestListenEventAccess() { permission.openSettings() }
        case .accessibility:

            let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
            if !AXIsProcessTrustedWithOptions(options) { permission.openSettings() }
        case .screenRecording:
            if !CGRequestScreenCaptureAccess() { permission.openSettings() }
        }
        refresh()
    }

    nonisolated private static func requestSpeech(_ done: @escaping @MainActor @Sendable () -> Void) {
        SFSpeechRecognizer.requestAuthorization { _ in
            Task { @MainActor in done() }
        }
    }

    func startPolling() {
        guard pollTimer == nil else { return }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            Task { @MainActor [weak self] in self?.refresh() }
        }
    }

    func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }

    func relaunch() {
        let bundlePath = Bundle.main.bundlePath
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        task.arguments = ["-c", "while kill -0 \(ProcessInfo.processInfo.processIdentifier) 2>/dev/null; do sleep 0.2; done; open \"\(bundlePath)\""]
        try? task.run()
        NSApplication.shared.terminate(nil)
    }
}
