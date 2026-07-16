import AppKit
import SwiftUI

extension Notification.Name {
    /// Posted after the settings dialog saves; daemons restart to pick it up.
    static let dockdConfigChanged = Notification.Name("DockdConfigChanged")
}

struct CycleEntry: Identifiable {
    let id = UUID()
    var match: String
    var label: String
}

struct SettingsView: View {
    @State private var sceneCollections: [String] = []
    @State private var dockedCollection: String = ""
    @State private var undockedCollection: String = ""
    @State private var dockMatch: String = ""
    @State private var haURL: String = ""
    @State private var haToken: String = ""
    @State private var toolsBinDir: String = ""
    @State private var loadError: String?
    @State private var outputCycle: [CycleEntry] = []
    @State private var inputCycle: [CycleEntry] = []
    @State private var outputDevices: [String] = []
    @State private var inputDevices: [String] = []

    var body: some View {
        Form {
            Section("OBS scene collections") {
                if let loadError {
                    Text(loadError).foregroundColor(.secondary).font(.caption)
                }
                Picker("Docked", selection: $dockedCollection) {
                    ForEach(pickerChoices(current: dockedCollection), id: \.self, content: Text.init)
                }
                Picker("Undocked", selection: $undockedCollection) {
                    ForEach(pickerChoices(current: undockedCollection), id: \.self, content: Text.init)
                }
            }
            Section("Dock detection") {
                TextField("Thunderbolt device match", text: $dockMatch)
            }
            Section("On-air light (Home Assistant)") {
                TextField("URL", text: $haURL)
                SecureField("Access token", text: $haToken)
            }
            cycleSection(
                title: "Quick Keys — output cycle (Out: button)",
                entries: $outputCycle,
                devices: outputDevices
            )
            cycleSection(
                title: "Quick Keys — input cycle (In: button)",
                entries: $inputCycle,
                devices: inputDevices
            )
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
        .frame(width: 520, height: 660)
        .onAppear(perform: load)
    }

    /// Editable device allow-list: device picker + short custom label
    /// (the Quick Keys display fits ~4-5 characters after the prefix).
    private func cycleSection(
        title: String, entries: Binding<[CycleEntry]>, devices: [String]
    ) -> some View {
        Section(title) {
            ForEach(entries) { $entry in
                HStack(spacing: 8) {
                    Picker("", selection: $entry.match) {
                        ForEach(deviceChoices(devices, current: entry.match), id: \.self, content: Text.init)
                    }
                    .labelsHidden()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    TextField("", text: $entry.label, prompt: Text("Label"))
                        .labelsHidden()
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 72)
                        .onChange(of: entry.label) { value in
                            if value.count > 5 { entry.label = String(value.prefix(5)) }
                        }
                    Button {
                        entries.wrappedValue.removeAll { $0.id == entry.id }
                    } label: {
                        Image(systemName: "minus.circle.fill")
                    }
                    .buttonStyle(.borderless)
                }
            }
            Button {
                entries.wrappedValue.append(
                    CycleEntry(match: devices.first ?? "", label: "")
                )
            } label: {
                Label("Add device", systemImage: "plus.circle")
            }
            .buttonStyle(.borderless)
        }
    }

    private func deviceChoices(_ devices: [String], current: String) -> [String] {
        var choices = devices
        if !current.isEmpty && !choices.contains(current) {
            choices.insert(current, at: 0)
        }
        return choices
    }

    private func pickerChoices(current: String) -> [String] {
        var choices = sceneCollections
        if !current.isEmpty && !choices.contains(current) {
            choices.append(current)
        }
        return choices
    }

    private func load() {
        dockedCollection = Config.string("obs.scene_collections.docked", default: "Docked")
        undockedCollection = Config.string("obs.scene_collections.undocked", default: "Undocked")
        dockMatch = Config.string("dock.match", default: "Thunderbolt 5 Hub")
        haURL = Config.string("onair.home_assistant.url", default: "")
        haToken = Config.string("onair.home_assistant.token", default: "")
        toolsBinDir = Config.string("tools.bin_dir", default: ToolRunner.binDir()?.path ?? "")
        outputCycle = loadCycle(
            "audio.output_cycle",
            fallback: [CycleEntry(match: "AirPods", label: "Pods"),
                       CycleEntry(match: "MacBook Pro Speakers", label: "Sys")]
        )
        inputCycle = loadCycle(
            "audio.input_cycle",
            fallback: [CycleEntry(match: "MacBook Pro Microphone", label: "Sys"),
                       CycleEntry(match: "AirPods", label: "Pods")]
        )
        ToolRunner.runAsync("dockd-obs", ["scene-collections"]) { result in
            if let list = result?["scene_collections"] as? [String] {
                sceneCollections = list
                loadError = nil
            } else {
                loadError = "Could not load scene collections from OBS (is it running?)"
            }
        }
        ToolRunner.runAsync("dockd-audio", ["list"]) { result in
            guard let devices = result?["devices"] as? [[String: Any]] else { return }
            outputDevices = devices
                .filter { $0["output"] as? Bool == true }
                .compactMap { $0["name"] as? String }
            inputDevices = devices
                .filter { $0["input"] as? Bool == true }
                .compactMap { $0["name"] as? String }
        }
    }

    private func loadCycle(_ key: String, fallback: [CycleEntry]) -> [CycleEntry] {
        guard let raw = Config.get(key) as? [[String: Any]] else { return fallback }
        let entries = raw.compactMap { dict -> CycleEntry? in
            guard let match = dict["match"] as? String else { return nil }
            return CycleEntry(match: match, label: dict["label"] as? String ?? "")
        }
        return entries.isEmpty ? fallback : entries
    }

    private func save() {
        Config.set("obs.scene_collections.docked", to: dockedCollection)
        Config.set("obs.scene_collections.undocked", to: undockedCollection)
        Config.set("dock.match", to: dockMatch)
        if !haURL.isEmpty { Config.set("onair.home_assistant.url", to: haURL) }
        if !haToken.isEmpty { Config.set("onair.home_assistant.token", to: haToken) }
        if !toolsBinDir.isEmpty { Config.set("tools.bin_dir", to: toolsBinDir) }
        Config.set("audio.output_cycle", to: serializeCycle(outputCycle))
        Config.set("audio.input_cycle", to: serializeCycle(inputCycle))
        NotificationCenter.default.post(name: .dockdConfigChanged, object: nil)
        NSApp.keyWindow?.close()
    }

    private func serializeCycle(_ entries: [CycleEntry]) -> [[String: String]] {
        entries
            .filter { !$0.match.isEmpty }
            .map { ["match": $0.match, "label": String($0.label.prefix(5))] }
    }
}

final class SettingsWindowController {
    private var window: NSWindow?

    func show() {
        if window == nil {
            let hosting = NSHostingController(rootView: SettingsView())
            let win = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 520, height: 660),
                styleMask: [.titled, .closable],
                backing: .buffered,
                defer: false
            )
            win.title = "Dockd Settings"
            win.isReleasedWhenClosed = false
            win.contentViewController = hosting
            win.setContentSize(NSSize(width: 520, height: 660))
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
