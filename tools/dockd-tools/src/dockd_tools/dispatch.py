"""Busybox-style entry point for the frozen (PyInstaller) build.

A single executable named ``dockd`` is shipped, with sibling symlinks
``dockd-audio``, ``dockd-obs``, … pointing at it. Which CLI runs is chosen from
``basename(sys.argv[0])`` — so the existing ``dockd-<name>`` contract the menubar
app depends on ([ToolRunner], [DaemonSupervisor]) keeps working unchanged.

Invoked directly as ``dockd`` (no ``-name`` suffix), the first positional
argument selects the CLI, which is handy for debugging: ``dockd audio list``.
"""

from __future__ import annotations

import importlib
import os
import sys

# Maps the executable suffix to its CLI module. Keep in sync with the
# ``[project.scripts]`` table in pyproject.toml.
COMMANDS = {
    "obs": "dockd_tools.cli.obs",
    "audio": "dockd_tools.cli.audio",
    "dock": "dockd_tools.cli.dock",
    "idle": "dockd_tools.cli.idle",
    "meeting": "dockd_tools.cli.meeting",
    "onair": "dockd_tools.cli.onair",
    "virtualcam-sleep": "dockd_tools.cli.virtualcam_sleep",
    "quickkeys": "dockd_tools.cli.quickkeys",
}


def _command_from_argv0() -> str | None:
    base = os.path.basename(sys.argv[0])
    if base.startswith("dockd-"):
        return base[len("dockd-"):]
    return None


def main() -> None:
    command = _command_from_argv0()
    if command is None:
        # Invoked as bare ``dockd``: take the command from argv[1].
        if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
            sys.stderr.write(
                "usage: dockd <" + "|".join(COMMANDS) + "> [args...]\n"
            )
            raise SystemExit(2)
        command = sys.argv.pop(1)

    module_name = COMMANDS.get(command)
    if module_name is None:
        sys.stderr.write(f"dockd: unknown command {command!r}\n")
        raise SystemExit(2)

    module = importlib.import_module(module_name)
    module.main()


if __name__ == "__main__":
    main()
