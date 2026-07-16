"""dockd-idle — seconds since last user input, plus screensaver timeout.

Example:
    dockd-idle            # {"ok": true, "idle_seconds": 3.2, "screensaver_timeout": 3600}
"""

from __future__ import annotations

import argparse

from ..cliutil import emit, fail
from ..idle import idle_seconds, screensaver_timeout


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(prog="dockd-idle", description=__doc__).parse_args(argv)
    try:
        emit(
            {
                "ok": True,
                "idle_seconds": round(idle_seconds(), 3),
                "screensaver_timeout": screensaver_timeout(),
            }
        )
    except Exception as exc:
        raise fail(f"idle detection failed: {exc}")


if __name__ == "__main__":
    main()
