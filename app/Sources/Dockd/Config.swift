import Foundation

/// Shared JSON config, same file the Python tools read:
/// ~/Library/Application Support/dockd/config.json (DOCKD_CONFIG overrides).
enum Config {
    static var path: URL {
        if let env = ProcessInfo.processInfo.environment["DOCKD_CONFIG"] {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/dockd/config.json")
    }

    static var logDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/dockd")
    }

    /// Shared daemon state dir (same one the Python tools use for heartbeats).
    static var stateDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/dockd/state")
    }

    /// Publish the current dock state for the Quick Keys daemon (which blanks
    /// the pad and ignores presses when undocked). Written atomically.
    static func writeDockState(_ docked: Bool) {
        let file = stateDir.appendingPathComponent("dock.json")
        guard let data = try? JSONSerialization.data(
            withJSONObject: ["docked": docked], options: []
        ) else { return }
        try? FileManager.default.createDirectory(
            at: stateDir, withIntermediateDirectories: true
        )
        let tmp = file.appendingPathExtension("tmp")
        do {
            try data.write(to: tmp)
            _ = try FileManager.default.replaceItemAt(file, withItemAt: tmp)
        } catch {
            try? data.write(to: file)  // best effort if atomic replace fails
        }
    }

    static func load() -> [String: Any] {
        guard let data = try? Data(contentsOf: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [:] }
        return json
    }

    /// Merge `values` into the config at a dotted path and save, preserving
    /// unrelated keys (the Python tools own the defaults).
    static func set(_ dotted: String, to value: Any) {
        var root = load()
        var keys = dotted.split(separator: ".").map(String.init)
        let last = keys.removeLast()
        func update(_ dict: inout [String: Any], _ remaining: [String]) {
            guard let head = remaining.first else {
                dict[last] = value
                return
            }
            var child = dict[head] as? [String: Any] ?? [:]
            update(&child, Array(remaining.dropFirst()))
            dict[head] = child
        }
        update(&root, keys)
        save(root)
    }

    static func get(_ dotted: String) -> Any? {
        var node: Any = load()
        for part in dotted.split(separator: ".") {
            guard let dict = node as? [String: Any], let next = dict[String(part)] else {
                return nil
            }
            node = next
        }
        return node
    }

    static func string(_ dotted: String, default def: String) -> String {
        get(dotted) as? String ?? def
    }

    private static func save(_ root: [String: Any]) {
        guard let data = try? JSONSerialization.data(
            withJSONObject: root, options: [.prettyPrinted, .sortedKeys]
        ) else { return }
        try? FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try? data.write(to: path)
    }
}
