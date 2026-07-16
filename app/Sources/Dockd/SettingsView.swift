import AppKit
import SwiftUI

struct SettingsView: View {
    @State private var profiles: [String] = []
    @State private var dockedProfile: String = ""
    @State private var undockedProfile: String = ""
    @State private var dockMatch: String = ""
    @State private var haURL: String = ""
    @State private var haToken: String = ""
    @State private var toolsBinDir: String = ""
    @State private var loadError: String?

    var body: some View {
        Form {
            Section("OBS profiles") {
                if let loadError {
                    Text(loadError).foregroundColor(.secondary).font(.caption)
                }
                Picker("Docked", selection: $dockedProfile) {
                    ForEach(pickerChoices(current: dockedProfile), id: \.self, content: Text.init)
                }
                Picker("Undocked", selection: $undockedProfile) {
                    ForEach(pickerChoices(current: undockedProfile), id: \.self, content: Text.init)
                }
            }
            Section("Dock detection") {
                TextField("Thunderbolt device match", text: $dockMatch)
            }
            Section("On-air light (Home Assistant)") {
                TextField("URL", text: $haURL)
                SecureField("Access token", text: $haToken)
            }
            Section("Tools") {
                TextField("dockd-tools bin dir", text: $toolsBinDir)
                    .font(.caption)
            }
            HStack {
                Button("Open Logs in Console") {
                    NSWorkspace.shared.open(Config.logDir)
                }
                Spacer()
                Button("Save") { save() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .formStyle(.grouped)
        .frame(width: 460, height: 430)
        .onAppear(perform: load)
    }

    private func pickerChoices(current: String) -> [String] {
        var choices = profiles
        if !current.isEmpty && !choices.contains(current) {
            choices.append(current)
        }
        return choices
    }

    private func load() {
        dockedProfile = Config.string("obs.profiles.docked", default: "Docked")
        undockedProfile = Config.string("obs.profiles.undocked", default: "Undocked")
        dockMatch = Config.string("dock.match", default: "Thunderbolt 5 Hub")
        haURL = Config.string("onair.home_assistant.url", default: "")
        haToken = Config.string("onair.home_assistant.token", default: "")
        toolsBinDir = Config.string("tools.bin_dir", default: ToolRunner.binDir()?.path ?? "")
        ToolRunner.runAsync("dockd-obs", ["profiles"]) { result in
            if let list = result?["profiles"] as? [String] {
                profiles = list
                loadError = nil
            } else {
                loadError = "Could not load profiles from OBS (is it running?)"
            }
        }
    }

    private func save() {
        Config.set("obs.profiles.docked", to: dockedProfile)
        Config.set("obs.profiles.undocked", to: undockedProfile)
        Config.set("dock.match", to: dockMatch)
        if !haURL.isEmpty { Config.set("onair.home_assistant.url", to: haURL) }
        if !haToken.isEmpty { Config.set("onair.home_assistant.token", to: haToken) }
        if !toolsBinDir.isEmpty { Config.set("tools.bin_dir", to: toolsBinDir) }
        NSApp.keyWindow?.close()
    }
}

final class SettingsWindowController {
    private var window: NSWindow?

    func show() {
        if window == nil {
            let hosting = NSHostingController(rootView: SettingsView())
            let win = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 460, height: 430),
                styleMask: [.titled, .closable],
                backing: .buffered,
                defer: false
            )
            win.title = "Dockd Settings"
            win.isReleasedWhenClosed = false
            win.contentViewController = hosting
            win.setContentSize(NSSize(width: 460, height: 430))
            window = win
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.center()
        window?.makeKeyAndOrderFront(nil)
        if let size = window?.contentView?.frame.size {
            AppDelegate.log.info("settings window shown; content size \(Int(size.width))x\(Int(size.height))")
        }
    }
}
