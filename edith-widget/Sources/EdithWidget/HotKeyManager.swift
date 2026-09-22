import AppKit

// Bare-modifier shortcuts (Control+Option with no other key, like Raycast's
// push-to-talk) can't be expressed with Carbon's RegisterEventHotKey, which
// requires a virtual key code. Watching NSEvent.flagsChanged and diffing the
// modifier set on each transition is the standard way to catch these globally.
// Requires the app to be granted Input Monitoring in System Settings > Privacy.
@MainActor
final class HotKeyManager {
    static let shared = HotKeyManager()

    private var monitor: Any?
    private var previousFlags: UInt = 0
    private var pressBindings: [UInt: () -> Void] = [:]
    private var holdBindings: [UInt: (press: () -> Void, release: () -> Void)] = [:]

    private init() {}

    /// Fires `action` the moment the flags transition to exactly `modifiers` pressed.
    /// Release is not observed — use `onModifierHold` for press/release pairs.
    func onModifierCombo(_ modifiers: NSEvent.ModifierFlags, action: @escaping () -> Void) {
        pressBindings[modifiers.rawValue] = action
        if monitor == nil { startMonitoring() }
    }

    /// True hold semantics: `onPress` fires the instant flags become exactly
    /// `modifiers`, `onRelease` fires the instant they stop being exactly
    /// `modifiers` (whether released cleanly or superseded by another key
    /// combo) — no second activation of the same combo needed to "stop".
    func onModifierHold(_ modifiers: NSEvent.ModifierFlags, onPress: @escaping () -> Void, onRelease: @escaping () -> Void) {
        holdBindings[modifiers.rawValue] = (onPress, onRelease)
        if monitor == nil { startMonitoring() }
    }

    private func startMonitoring() {
        monitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask).rawValue
            Task { @MainActor in self?.handle(flags) }
        }
    }

    private func handle(_ flags: UInt) {
        let previous = previousFlags
        previousFlags = flags
        guard flags != previous else { return }
        if let hold = holdBindings[previous] { hold.release() }
        if let hold = holdBindings[flags] { hold.press() }
        if let action = pressBindings[flags] { action() }
    }

    // HotKeyManager.shared lives for the process lifetime; deinit never runs, and
    // Swift 6 disallows touching the non-Sendable `Any?` monitor token from a
    // (necessarily nonisolated) deinit anyway.
}
