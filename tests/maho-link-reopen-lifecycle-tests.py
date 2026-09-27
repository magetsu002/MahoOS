#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT / "config/quickshell/maho-link/shell.qml").read_text(encoding="utf-8")


def check(name: str, ok: bool) -> None:
    if not ok:
        raise AssertionError(name)
    print(f"PASS  {name}")


check("foreground carrier is lifetime-mapped", "visible: true" in SHELL)
check("foreground carrier is never remapped by lifecycle state", "materialMapped" not in SHELL)
check("synthetic reveal timer is absent", "launchRevealDelay" not in SHELL)
check("close removes input authority", "overlayOpen = false" in SHELL)
check("closed carrier mask is null", "root.overlayOpen ? linkSurface : null" in SHELL)

reveal = SHELL[SHELL.index("function revealSurfaceWhenReady()"):SHELL.index("function finishLaunchReveal()")]
check(
    "launch placement commits before reveal turn",
    reveal.index("commitLaunchPlacement()") < reveal.index("Qt.callLater(root.finishLaunchReveal)"),
)

finish = SHELL[SHELL.index("function finishLaunchReveal()"):SHELL.index("function showMode(")]
check(
    "final x/y are restored before material becomes visible",
    finish.index("linkSurface.x = launchPlacementX") < finish.index("linkSurface.shown = true")
    and finish.index("linkSurface.y = launchPlacementY") < finish.index("linkSurface.shown = true"),
)

class ReusedProcess:
    def __init__(self) -> None:
        self.carrier_mapped = True
        self.positions = {"wifi": (288.0, 236.0), "bluetooth": (599.0, 279.0)}
        self.visible_frames: list[tuple[str, float, float]] = []
        self.open_mode: str | None = None

    def open(self, mode: str) -> None:
        assert self.carrier_mapped
        x, y = self.positions[mode]
        assert x > 0 and y > 0
        self.open_mode = mode
        self.visible_frames.append((mode, x, y))

    def close(self) -> None:
        assert self.carrier_mapped
        self.open_mode = None


process = ReusedProcess()

for mode in ("wifi", "bluetooth"):
    for _ in range(20):
        process.open(mode)
        process.close()

process.open("wifi")
process.close()
process.open("wifi")
process.close()
process.open("wifi")

for mode in ("wifi", "bluetooth", "wifi"):
    process.close()
    process.open(mode)

check("carrier stayed mapped through all process-reuse cycles", process.carrier_mapped)
check("20+ Wi-Fi presentations kept authoritative coordinates", sum(1 for m, _, _ in process.visible_frames if m == "wifi") >= 20)
check("20+ Bluetooth presentations kept authoritative coordinates", sum(1 for m, _, _ in process.visible_frames if m == "bluetooth") >= 20)
check(
    "no modeled visible presentation used default/top-left coordinates",
    all(x > 0 and y > 0 for _, x, y in process.visible_frames),
)
check(
    "mode switches preserve independent position authority",
    all((x, y) == process.positions[mode] for mode, x, y in process.visible_frames),
)

print("ALL MAHO LINK REOPEN LIFECYCLE TESTS PASS")
