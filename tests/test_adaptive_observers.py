#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_observers import ProcessEvidence, SessionEvidence, WindowEvidence, classify_workload


def p(pid, name, *, ppid=1, age=30, cpu=5, foreground=False, gpu=False):
    return ProcessEvidence(pid, ppid, name, name, age, cpu, foreground, gpu)


def main() -> None:
    recent = SessionEvidence(False, 0, 0, 1, ())
    idle = SessionEvidence(True, 600, 600, 600, ())

    steam = classify_workload([p(10, "steam", age=500, cpu=50)], WindowEvidence(False, 10, "Steam", "steam"), recent)
    assert steam.probable_gaming is False
    assert "gaming:launcher-only-insufficient" in steam.evidence

    brief_gcc = classify_workload([p(20, "gcc", age=1, cpu=.1)], WindowEvidence(False, None), idle)
    assert brief_gcc.probable_compile is False
    assert "compile:process-exists-insufficient" in brief_gcc.evidence

    build = [p(30, "ninja", age=120, cpu=5), p(31, "gcc", ppid=30, age=20, cpu=8)]
    compile_job = classify_workload(build, WindowEvidence(False, None), idle)
    assert compile_job.probable_compile is True
    assert compile_job.respected_background_job is True
    # Locked does not erase meaningful compute work.
    assert compile_job.probable_compile is True and idle.locked is True

    game = [p(40, "gamescope", age=300, cpu=30, foreground=True, gpu=True)]
    gaming = classify_workload(game, WindowEvidence(True, 40, "Game", "game"), recent)
    assert gaming.probable_gaming is True
    assert gaming.interactive is True
    assert gaming.gpu_activity is True

    video = [p(50, "mpv", age=300, cpu=12, foreground=True)]
    media = classify_workload(video, WindowEvidence(True, 50, "Movie", "mpv"), recent, audio_active=True)
    assert media.probable_media is True
    assert media.probable_gaming is False

    render = classify_workload([p(60, "blender", age=180, cpu=120)], WindowEvidence(False, None), idle)
    assert render.probable_rendering is True
    assert render.respected_background_job is True

    empty = classify_workload([], WindowEvidence(), SessionEvidence())
    assert empty.confidence == "unknown"
    assert empty.probable_gaming is False

    print("ALL ADAPTIVE OBSERVER TESTS PASS")


if __name__ == "__main__":
    main()
