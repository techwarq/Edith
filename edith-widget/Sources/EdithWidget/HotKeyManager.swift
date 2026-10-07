import AppKit

@MainActor
final class HotKeyManager {
    static let shared = HotKeyManager()

    private var monitor: Any?
    private var previousFlags: UInt = 0
    private var pressBindings: [UInt: () -> Void] = [:]
    private var holdBindings: [UInt: (press: () -> Void, release: () -> Void)] = [:]

    private static let chordModifiers: NSEvent.ModifierFlags = [.control, .option, .command, .shift]

    private init() {}

    func onModifierCombo(_ modifiers: NSEvent.ModifierFlags, action: @escaping () -> Void) {
        pressBindings[modifiers.rawValue] = action
        if monitor == nil { startMonitoring() }
    }

    func onModifierHold(_ modifiers: NSEvent.ModifierFlags, onPress: @escaping () -> Void, onRelease: @escaping () -> Void) {
        holdBindings[modifiers.rawValue] = (onPress, onRelease)
        if monitor == nil { startMonitoring() }
    }

    private var keyDownMonitor: Any?

    func onKeyDown(_ keyCode: UInt16, action: @escaping () -> Void) {
        keyDownMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            guard event.keyCode == keyCode else { return }
            Task { @MainActor in action() }
        }
    }

    private var localMonitor: Any?

    private func startMonitoring() {

        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
            let flags = event.modifierFlags.intersection(HotKeyManager.chordModifiers).rawValue
            Task { @MainActor in self?.handle(flags) }
            return event
        }
        monitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in

            let flags = event.modifierFlags.intersection(HotKeyManager.chordModifiers).rawValue
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

}
