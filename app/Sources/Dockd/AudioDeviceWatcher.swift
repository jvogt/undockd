import CoreAudio
import Foundation
import os

/// Fires a callback (debounced) whenever the default input/output device or
/// the device list changes — so the menubar icon reacts instantly instead of
/// waiting for the next poll.
final class AudioDeviceWatcher {
    private static let log = Logger(subsystem: "com.jvogt.dockd", category: "audiowatch")

    private let onChange: () -> Void
    private var debounce: DispatchWorkItem?
    private var installed: [(AudioObjectPropertyAddress)] = []
    private var listenerBlock: AudioObjectPropertyListenerBlock!

    private static let selectors: [AudioObjectPropertySelector] = [
        kAudioHardwarePropertyDefaultInputDevice,
        kAudioHardwarePropertyDefaultOutputDevice,
        kAudioHardwarePropertyDevices,
    ]

    init(onChange: @escaping () -> Void) {
        self.onChange = onChange
        listenerBlock = { [weak self] _, _ in
            self?.scheduleFire()
        }
        for selector in Self.selectors {
            var address = AudioObjectPropertyAddress(
                mSelector: selector,
                mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain
            )
            let status = AudioObjectAddPropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, .main, listenerBlock
            )
            if status == noErr {
                installed.append(address)
            } else {
                Self.log.error("failed to install audio listener \(selector): \(status)")
            }
        }
        Self.log.info("audio device watcher installed (\(self.installed.count) listeners)")
    }

    private func scheduleFire() {
        // Device switches emit bursts of notifications; coalesce them.
        debounce?.cancel()
        let work = DispatchWorkItem { [weak self] in
            Self.log.debug("audio device change detected")
            self?.onChange()
        }
        debounce = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }

    deinit {
        for var address in installed {
            AudioObjectRemovePropertyListenerBlock(
                AudioObjectID(kAudioObjectSystemObject), &address, .main, listenerBlock
            )
        }
    }
}
