import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let viewModel = WidgetViewModel()
    private var panel: WidgetPanel?

    // Bare Control is the modifier used in a huge number of unrelated system/app
    // shortcuts (Control+click, Control+C, Mission Control, Control+Command
    // below, ...) — every one of those passes through a "Control alone"
    // instant on the way down/up. A held-for-this-long gate stops those quick
    // incidental taps from starting a recording; a deliberate hold-to-talk
    // still feels instant against a ~200ms threshold.
    private static let voiceHoldThreshold: TimeInterval = 0.2
    private var pendingVoiceStart: DispatchWorkItem?
    private var voiceCaptureActive = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory) // no Dock icon, no menu bar — pure widget

        let panel = WidgetPanel(viewModel: viewModel)
        self.panel = panel
        panel.orderFrontRegardless()

        // Control (held alone): true push-to-talk — starts the instant it's
        // held past the threshold, stops the instant it's released, however
        // short. Control+Command: bring the panel forward and focus the text
        // field to type instead of speaking.
        HotKeyManager.shared.onModifierHold([.control], onPress: { [weak self] in
            guard let self else { return }
            let work = DispatchWorkItem { [weak self] in
                guard let self else { return }
                self.voiceCaptureActive = true
                self.panel?.orderFrontRegardless()
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
        HotKeyManager.shared.onModifierCombo([.control, .command]) { [weak self] in
            guard let self, let panel = self.panel else { return }
            panel.makeKeyAndOrderFront(nil)
            self.viewModel.requestTextFocus()
        }
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()
