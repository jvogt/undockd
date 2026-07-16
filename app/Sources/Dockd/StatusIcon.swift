import AppKit

/// Renders the menubar icon for the current state.
///
/// - AirPods available but not active output: outlined (dimmed) airpods
/// - AirPods active output: solid airpods
/// - AirPods active output AND input: airpods with a mic badge
/// - AirPods not available: speaker
/// A small red dot is overlaid when on air.
enum StatusIcon {
    static func image(for state: DockdState) -> NSImage {
        let base: NSImage
        let available = state.airpodsAvailable ?? state.airpodsConnected
        if available {
            if state.airpodsActiveOutput && state.airpodsActiveInput {
                base = composite(symbol: "airpods", badge: "mic.fill", alpha: 1.0)
            } else if state.airpodsActiveOutput {
                base = symbolImage("airpods", alpha: 1.0, weight: .bold)
            } else {
                base = symbolImage("airpods", alpha: 0.35, weight: .light)
            }
        } else {
            base = symbolImage("speaker.wave.2", alpha: 1.0)
        }
        if state.onAir {
            return composite(base: base, dotColor: .systemRed)
        }
        return base
    }

    static func tooltip(for state: DockdState) -> String {
        var parts: [String] = []
        let available = state.airpodsAvailable ?? state.airpodsConnected
        if state.airpodsActiveOutput {
            parts.append(state.airpodsActiveInput
                ? "AirPods: output + input (click to switch away)"
                : "AirPods: active output (click to switch away)")
        } else if available {
            parts.append("AirPods available (click to use)")
        } else {
            parts.append("System output (no AirPods)")
        }
        if state.onAir { parts.append("ON AIR") }
        return parts.joined(separator: " — ")
    }

    private static func symbolImage(
        _ name: String, alpha: CGFloat, weight: NSFont.Weight = .regular
    ) -> NSImage {
        let config = NSImage.SymbolConfiguration(pointSize: 16, weight: weight)
        let symbol = NSImage(systemSymbolName: name, accessibilityDescription: name)?
            .withSymbolConfiguration(config) ?? NSImage()
        if alpha >= 1.0 {
            symbol.isTemplate = true
            return symbol
        }
        let size = symbol.size
        let faded = NSImage(size: size, flipped: false) { rect in
            symbol.draw(in: rect, from: .zero, operation: .sourceOver, fraction: alpha)
            return true
        }
        faded.isTemplate = true
        return faded
    }

    private static func composite(symbol: String, badge: String, alpha: CGFloat) -> NSImage {
        let base = symbolImage(symbol, alpha: alpha)
        let badgeConfig = NSImage.SymbolConfiguration(pointSize: 8, weight: .bold)
        guard let badgeImage = NSImage(systemSymbolName: badge, accessibilityDescription: badge)?
            .withSymbolConfiguration(badgeConfig)
        else { return base }
        let size = NSSize(width: base.size.width + 4, height: base.size.height)
        let out = NSImage(size: size, flipped: false) { _ in
            base.draw(at: .zero, from: .zero, operation: .sourceOver, fraction: 1.0)
            badgeImage.draw(
                at: NSPoint(x: size.width - badgeImage.size.width, y: 0),
                from: .zero, operation: .sourceOver, fraction: 1.0
            )
            return true
        }
        out.isTemplate = true
        return out
    }

    /// Non-template overlay (red on-air dot) — keeps color in the menubar.
    private static func composite(base: NSImage, dotColor: NSColor) -> NSImage {
        let size = base.size
        let out = NSImage(size: size, flipped: false) { _ in
            base.draw(at: .zero, from: .zero, operation: .sourceOver, fraction: 1.0)
            let dot = NSRect(x: size.width - 6, y: size.height - 6, width: 5, height: 5)
            dotColor.setFill()
            NSBezierPath(ovalIn: dot).fill()
            return true
        }
        out.isTemplate = false
        return out
    }
}
