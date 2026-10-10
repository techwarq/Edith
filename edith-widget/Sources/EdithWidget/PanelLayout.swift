import AppKit
import Combine

@MainActor
final class PanelLayout: ObservableObject {
    static let shared = PanelLayout()

    static let minSize = CGSize(width: 340, height: 280)
    static let defaultWidth: CGFloat = 440
    private static let widthKey = "panelWidth"
    private static let heightKey = "panelHeight"

    @Published private(set) var size: CGSize

    private init() {
        let defaults = UserDefaults.standard
        let width = defaults.double(forKey: Self.widthKey)
        let height = defaults.double(forKey: Self.heightKey)
        let fullHeight = Self.screen()?.visibleFrame.height ?? 700
        size = Self.clamp(CGSize(width: width > 0 ? width : Self.defaultWidth, height: height > 0 ? height : fullHeight))
    }

    var isFullHeight: Bool {
        guard let visible = Self.screen()?.visibleFrame else { return false }
        return size.height >= visible.height - 1
    }

    func resize(to proposed: CGSize) {
        let next = Self.clamp(proposed)
        guard next != size else { return }
        size = next
        UserDefaults.standard.set(next.width, forKey: Self.widthKey)
        UserDefaults.standard.set(next.height, forKey: Self.heightKey)
    }

    func toggleFullHeight() {
        let full = Self.screen()?.visibleFrame.height ?? size.height
        resize(to: CGSize(width: size.width, height: isFullHeight ? max(Self.minSize.height, full * 0.55) : full))
    }

    static func clamp(_ proposed: CGSize) -> CGSize {
        let visible = screen()?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        return CGSize(
            width: min(max(proposed.width, minSize.width), visible.width * 0.7).rounded(),
            height: min(max(proposed.height, minSize.height), visible.height).rounded()
        )
    }

    static func screen() -> NSScreen? {
        let mouse = NSEvent.mouseLocation
        return NSScreen.screens.first(where: { NSMouseInRect(mouse, $0.frame, false) }) ?? NSScreen.main
    }
}
