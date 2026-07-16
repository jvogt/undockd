import Foundation
import os

struct DockdState: Equatable {
    var docked: Bool?
    var airpodsAvailable: Bool?   // nil = bluetooth unreadable
    var airpodsConnected = false
    var airpodsActiveOutput = false
    var airpodsActiveInput = false
    var obsRunning = false
    var virtualcamActive = false
    var currentSceneCollection: String?
    var onAir = false
    var inMeeting = false
    var onairHealthy = false
    var camSleepHealthy = false
    var quickkeysHealthy = false
    var quickkeysConnected = false
}

/// Polls the dockd CLIs, applies the dock automation rules, and supervises
/// the daemons. All state mutation happens on the main queue.
final class StateModel {
    static let log = Logger(subsystem: "com.jvogt.dockd", category: "state")

    private(set) var state = DockdState()
    var onChange: ((DockdState) -> Void)?

    private let camSleep = DaemonSupervisor(
        name: "virtualcam-sleep", tool: "dockd-virtualcam-sleep", args: ["run"]
    )
    private let onair = DaemonSupervisor(name: "onair", tool: "dockd-onair", args: ["run"])
    // Always-on: the Quick Keys pad is a USB desk peripheral, not gated on the
    // dock/on-air state like `onair` is.
    private let quickKeys = DaemonSupervisor(
        name: "quickkeys", tool: "dockd-quickkeys", args: ["run"]
    )
    private var timer: Timer?
    private var dockTimer: Timer?
    private var onairTimer: Timer?
    private var polling = false
    private var repollRequested = false
    private var pollCount = 0
    private var audioPolling = false
    private var audioWatcher: AudioDeviceWatcher?
    /// Dock state the OBS scene-collection automation last acted on.
    private var appliedDockState: Bool?

    func start() {
        camSleep.start()
        quickKeys.start()
        // React to device swaps instantly instead of waiting for the timer.
        audioWatcher = AudioDeviceWatcher { [weak self] in
            self?.pollAudio()
        }
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.poll()
        }
        // Dock detection runs on its own light path (just dockd-dock, applied
        // immediately) so a slow AirPods/OBS status in the main poll can never
        // delay dock/undock reaction.
        checkDockOnly()
        dockTimer = Timer.scheduledTimer(withTimeInterval: 6, repeats: true) { [weak self] _ in
            self?.checkDockOnly()
        }
        // Track on-air/mute state by reading the daemon's heartbeat directly
        // (~1s, no subprocess) so the menubar icon keeps up with the pad rather
        // than lagging behind the 3s main poll.
        readOnairState()
        onairTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            self?.readOnairState()
        }
    }

    func shutdown() {
        timer?.invalidate()
        dockTimer?.invalidate()
        onairTimer?.invalidate()
        camSleep.stop()
        onair.stop()
        quickKeys.stop()
    }

    /// Read the on-air daemon's heartbeat file directly for fast icon updates.
    /// Freshness (recent timestamp) stands in for health; a stopped daemon
    /// (undocked) goes stale and reads as not-on-air within a few seconds.
    private func readOnairState() {
        let file = Config.stateDir.appendingPathComponent("onair.json")
        var healthy = false, onAir = false, inMeeting = false
        if let data = try? Data(contentsOf: file),
           let hb = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let ts = hb["ts"] as? Double ?? 0
            let interval = hb["interval"] as? Double ?? 1
            healthy = Date().timeIntervalSince1970 - ts < interval * 2 + 5
            if healthy {
                onAir = hb["on_air"] as? Bool ?? false
                inMeeting = hb["in_meeting"] as? Bool ?? false
            }
        }
        var next = state
        next.onairHealthy = healthy
        next.onAir = onAir
        next.inMeeting = inMeeting
        if next != state {
            state = next
            onChange?(next)
        }
    }

    /// Re-check the dock now, ahead of the normal cadence. Called from a
    /// display attach/detach (a strong dock signal). Undock is instant, but a
    /// freshly-plugged Thunderbolt dock can take many seconds to enumerate into
    /// system_profiler, so probe in a decaying burst rather than once.
    func recheckDock() {
        for delay in [0.0, 2, 4, 7, 11, 16, 22] as [Double] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                self?.checkDockOnly()
            }
        }
    }

    private func probeDock() -> Bool? {
        ToolRunner.run("dockd-dock", ["status"], timeout: 15)?["docked"] as? Bool
    }

    /// Lightweight dock probe (spawns just dockd-dock). A state *change* is
    /// confirmed by a second probe ~1.5s later before it is applied: docking a
    /// Thunderbolt bus makes system_profiler briefly report the tree without the
    /// hub, which otherwise shows up as a spurious undock/redock flap.
    private func checkDockOnly() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self, let reading = self.probeDock() else { return }
            DispatchQueue.main.async {
                guard self.state.docked != reading else { return }
                if self.state.docked == nil {
                    self.applyDock(reading)  // first detection — nothing to flap against
                    return
                }
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 1.5) { [weak self] in
                    guard let self, let confirm = self.probeDock() else { return }
                    DispatchQueue.main.async {
                        // Only flip if the change persisted and nothing else
                        // already applied it in the meantime.
                        guard confirm == reading, self.state.docked != reading else { return }
                        Self.log.info("dock change confirmed: \(reading ? "docked" : "undocked", privacy: .public)")
                        self.applyDock(reading)
                    }
                }
            }
        }
    }

    private func applyDock(_ docked: Bool) {
        guard state.docked != docked else { return }
        var next = state
        next.docked = docked
        let previous = state
        state = next
        applyAutomations(current: next)
        if next != previous { onChange?(next) }
    }

    func poll() {
        guard !polling else {
            repollRequested = true  // run again as soon as the current poll ends
            return
        }
        polling = true
        pollCount += 1
        // Dock state has its own light path (checkDockOnly); the main poll only
        // covers AirPods/OBS/daemon health. Do the full (IOBluetooth) AirPods
        // availability check every 4th cycle, a CoreAudio-only fast check otherwise.
        let fullAirpods = pollCount % 4 == 2 || pollCount == 1
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            // Start from the previous state so one failed tool doesn't
            // read as a state change.
            var next = self.state

            let airpodsArgs = fullAirpods
                ? ["airpods", "status"] : ["airpods", "status", "--fast"]
            if let pods = ToolRunner.run("dockd-audio", airpodsArgs) {
                Self.merge(airpods: pods, into: &next, fullCheck: fullAirpods)
            }
            if let obs = ToolRunner.run("dockd-obs", ["status"]) {
                next.obsRunning = obs["running"] as? Bool ?? false
                next.virtualcamActive = obs["virtualcam_active"] as? Bool ?? false
                next.currentSceneCollection = obs["current_scene_collection"] as? String
            }
            // on-air/mute state comes from readOnairState() (fast heartbeat read).
            if let camStatus = ToolRunner.run("dockd-virtualcam-sleep", ["status"]) {
                next.camSleepHealthy = camStatus["healthy"] as? Bool ?? false
            }
            if let qkStatus = ToolRunner.run("dockd-quickkeys", ["status"]) {
                next.quickkeysHealthy = qkStatus["healthy"] as? Bool ?? false
                next.quickkeysConnected = qkStatus["connected"] as? Bool ?? false
            }

            DispatchQueue.main.async {
                self.polling = false
                let previous = self.state
                self.state = next
                self.applyAutomations(current: next)
                if next != previous {
                    self.onChange?(next)
                }
                if self.repollRequested {
                    self.repollRequested = false
                    self.poll()
                }
            }
        }
    }

    /// Merge a `dockd-audio airpods status` payload into the state. On fast
    /// (CoreAudio-only) checks, `available` is unknown — keep the last full
    /// reading, but let a connected device imply availability.
    private static func merge(airpods pods: [String: Any], into next: inout DockdState, fullCheck: Bool) {
        if fullCheck, let available = pods["available"] as? Bool {
            next.airpodsAvailable = available
        }
        next.airpodsConnected = pods["connected"] as? Bool ?? false
        next.airpodsActiveOutput = pods["active_output"] as? Bool ?? false
        next.airpodsActiveInput = pods["active_input"] as? Bool ?? false
        if next.airpodsConnected {
            next.airpodsAvailable = true
        }
    }

    /// Fast, audio-only refresh triggered by CoreAudio device notifications.
    func pollAudio() {
        guard !audioPolling else { return }
        audioPolling = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let pods = ToolRunner.run("dockd-audio", ["airpods", "status", "--fast"], timeout: 10)
            DispatchQueue.main.async {
                self.audioPolling = false
                guard let pods else { return }
                var next = self.state
                Self.merge(airpods: pods, into: &next, fullCheck: false)
                if next != self.state {
                    Self.log.info("audio device change applied to state")
                    self.state = next
                    self.onChange?(next)
                }
            }
        }
    }

    /// README behavior: docked → mapped "Docked" scene collection + on-air
    /// watch on; undocked → mapped "Undocked" scene collection + on-air watch
    /// off. OBS is
    /// started if it should be running but isn't.
    private func applyAutomations(current: DockdState) {
        guard let docked = current.docked else { return }

        if docked {
            if !onair.isRunning { onair.start() }
        } else {
            if onair.isRunning { onair.stop() }
        }

        guard docked != appliedDockState else { return }
        appliedDockState = docked
        // Publish for the Quick Keys daemon: it blanks the pad and ignores
        // presses while undocked, and relights the moment this flips back.
        Config.writeDockState(docked)

        let slot = docked ? "docked" : "undocked"
        Self.log.info("dock state: \(docked ? "docked" : "undocked", privacy: .public); applying scene-collection slot \(slot, privacy: .public)")
        DispatchQueue.global(qos: .userInitiated).async {
            if !current.obsRunning {
                ToolRunner.run("dockd-obs", ["ensure-running"], timeout: 30)
            }
            ToolRunner.run("dockd-obs", ["scene-collection", "set", "--slot", slot])
            DispatchQueue.main.async { self.poll() }
        }
    }

    // MARK: - user actions

    /// Menubar click behavior: toggle AirPods as output when possible.
    func toggleAirpods(completion: @escaping ([String: Any]?) -> Void) {
        ToolRunner.runAsync("dockd-audio", ["airpods", "toggle"], timeout: 30) { result in
            // The toggle result carries the fresh AirPods status — apply it
            // immediately so the icon updates without waiting for a poll.
            if let result, result["ok"] as? Bool == true {
                var next = self.state
                if let value = result["available"] as? Bool { next.airpodsAvailable = value }
                next.airpodsConnected = result["connected"] as? Bool ?? next.airpodsConnected
                next.airpodsActiveOutput = result["active_output"] as? Bool ?? next.airpodsActiveOutput
                next.airpodsActiveInput = result["active_input"] as? Bool ?? next.airpodsActiveInput
                if next != self.state {
                    self.state = next
                    self.onChange?(next)
                }
            } else if let error = result?["error"] as? String {
                // e.g. AirPods bonded to a phone won't answer a Bluetooth page.
                Self.log.info("airpods toggle failed: \(error, privacy: .public)")
            }
            self.poll()
            completion(result)
        }
    }

    func toggleVirtualcam() {
        ToolRunner.runAsync("dockd-obs", ["virtualcam", "toggle"]) { _ in self.poll() }
    }

    /// Bounce the daemons so they pick up config changes.
    func restartDaemons() {
        camSleep.restart()
        onair.restart()
        quickKeys.restart()
    }
}
