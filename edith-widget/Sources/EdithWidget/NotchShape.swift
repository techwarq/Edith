import SwiftUI

struct NotchShape: Shape {
    var flare: CGFloat
    var radius: CGFloat

    var animatableData: AnimatablePair<CGFloat, CGFloat> {
        get { AnimatablePair(flare, radius) }
        set { flare = newValue.first; radius = newValue.second }
    }

    func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        let f = min(flare, h / 4)
        let r = min(radius, (h - 2 * f) / 2, w - f)

        var p = Path()
        p.move(to: CGPoint(x: 0, y: 0))
        p.addQuadCurve(to: CGPoint(x: f, y: f), control: CGPoint(x: 0, y: f))
        p.addLine(to: CGPoint(x: w - r, y: f))
        p.addArc(tangent1End: CGPoint(x: w, y: f), tangent2End: CGPoint(x: w, y: f + r), radius: r)
        p.addLine(to: CGPoint(x: w, y: h - f - r))
        p.addArc(tangent1End: CGPoint(x: w, y: h - f), tangent2End: CGPoint(x: w - r, y: h - f), radius: r)
        p.addLine(to: CGPoint(x: f, y: h - f))
        p.addQuadCurve(to: CGPoint(x: 0, y: h), control: CGPoint(x: 0, y: h - f))
        p.closeSubpath()
        return p
    }
}
