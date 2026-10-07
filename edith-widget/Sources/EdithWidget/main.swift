import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let viewModel = WidgetViewModel()
    private var panel: WidgetPanel?

    private static let voiceHoldThreshold: TimeInterval = 0.2
    private var pendingVoiceStart: DispatchWorkItem?
    private var voiceCaptureActive = false

    func applicationWillTerminate(_ notification: Notification) {
        ServerLauncher.shared.shutdown()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let panel = WidgetPanel(viewModel: viewModel)
        self.panel = panel
        panel.orderFrontRegardless()

        HotKeyManager.shared.onModifierHold([.control], onPress: { [weak self] in
            guard let self else { return }
            let work = DispatchWorkItem { [weak self] in
                guard let self else { return }
                self.voiceCaptureActive = true
                self.viewModel.beginVoiceCapture()
            }
            self.pendingVoiceStart = work
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.voiceHoldThreshold, execute: work)
        }, onRelease: { [weak self] in
            guard let self else { return }
            self.pendingVoiceStart?.cancel()
            self.pendingVoiceStart = nil
            if self.voiceCaptureActive {
                self.voiceCaptureActive = false
                self.viewModel.endVoiceCapture()
            }
        })

        HotKeyManager.shared.onKeyDown(53) { [weak self] in
            guard let self, self.viewModel.isBusy else { return }
            self.viewModel.stopWork()
        }
        HotKeyManager.shared.onModifierCombo([.control, .command]) { [weak self] in
            self?.viewModel.toggleTyping()
        }
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
