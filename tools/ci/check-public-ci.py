#!/usr/bin/env python3
"""Static policy checks for public GitHub Actions and uploaded CI evidence."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
ALLOWED_ACTIONS = {
    "actions/checkout": "v4",
    "actions/upload-artifact": "v4",
}
ALLOWED_HOME_NAMES = {"runner", "tester", "maho-ci", "root"}
MAX_PUBLIC_TEXT_ARTIFACT = 2 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)
RISKY_LOG_PATTERNS = (
    re.compile(r"(?m)^\s*printenv(?:\s|$)"),
    re.compile(r"(?m)^\s*env\s*\|"),
    re.compile(r"(?m)^\s*set\s+-x(?:\s|$)"),
    re.compile(r"toJson\(secrets\)", re.IGNORECASE),
    re.compile(r"toJson\(github\)", re.IGNORECASE),
)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def workflow_events(document: dict) -> tuple[dict, set[str]]:
    trigger = document.get("on", document.get(True))
    if isinstance(trigger, str):
        return {trigger: None}, {trigger}
    if isinstance(trigger, list):
        return {str(item): None for item in trigger}, {str(item) for item in trigger}
    if isinstance(trigger, dict):
        return trigger, {str(key) for key in trigger}
    return {}, set()


def check_workflows() -> int:
    try:
        import yaml  # type: ignore
    except ImportError:
        print("FAIL PyYAML is required for workflow structure validation", file=sys.stderr)
        return 1

    errors: list[str] = []
    workflows = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))
    if not workflows:
        print("FAIL no GitHub Actions workflows found", file=sys.stderr)
        return 1

    for path in workflows:
        rel = path.relative_to(ROOT)
        raw = path.read_text()
        try:
            document = yaml.safe_load(raw)
        except Exception as exc:
            fail(errors, f"{rel}: invalid YAML: {exc}")
            continue
        if not isinstance(document, dict):
            fail(errors, f"{rel}: workflow root must be a mapping")
            continue

        trigger_map, events = workflow_events(document)
        if "pull_request_target" in events:
            fail(errors, f"{rel}: pull_request_target is forbidden for public contribution workflows")

        permissions = document.get("permissions")
        if permissions != {"contents": "read"}:
            fail(errors, f"{rel}: top-level permissions must be exactly contents: read")

        concurrency = document.get("concurrency")
        if not isinstance(concurrency, dict) or not concurrency.get("group") or "cancel-in-progress" not in concurrency:
            fail(errors, f"{rel}: concurrency group and cancel-in-progress are required")
        elif concurrency.get("cancel-in-progress") is False and events != {"workflow_dispatch"}:
            fail(errors, f"{rel}: non-cancelling concurrency is reserved for manual-only certification")

        if path.name != "public-ci.yml":
            for event in ("push", "pull_request"):
                if event not in events:
                    continue
                config = trigger_map.get(event)
                if not isinstance(config, dict) or not (config.get("paths") or config.get("paths-ignore")):
                    fail(errors, f"{rel}: {event} must be path-scoped unless it is the universal public gate")

        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            fail(errors, f"{rel}: jobs mapping is required")
            continue

        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                fail(errors, f"{rel}: job {job_name!r} must be a mapping")
                continue
            if "runs-on" not in job:
                continue
            timeout = job.get("timeout-minutes")
            if not isinstance(timeout, int) or not 1 <= timeout <= 60:
                fail(errors, f"{rel}: hosted job {job_name!r} needs timeout-minutes in range 1..60")
            runner = job.get("runs-on")
            runner_text = " ".join(runner) if isinstance(runner, list) else str(runner)
            if "pull_request" in events and "self-hosted" in runner_text:
                fail(errors, f"{rel}: public pull requests must not target self-hosted runners")

            for step in job.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and not uses.startswith("./"):
                    action, sep, version = uses.partition("@")
                    if not sep or ALLOWED_ACTIONS.get(action) != version:
                        fail(errors, f"{rel}: action {uses!r} is not in the public CI allowlist")
                if uses == "actions/upload-artifact@v4":
                    with_block = step.get("with")
                    if not isinstance(with_block, dict):
                        fail(errors, f"{rel}: upload-artifact step is missing with:")
                        continue
                    retention = with_block.get("retention-days")
                    if not isinstance(retention, int) or not 1 <= retention <= 30:
                        fail(errors, f"{rel}: uploaded artifacts need retention-days in range 1..30")
                    artifact_path = str(with_block.get("path", "")).strip()
                    if not artifact_path:
                        fail(errors, f"{rel}: upload-artifact path is empty")
                    if artifact_path in {".", "/", "~", "$HOME"}:
                        fail(errors, f"{rel}: upload-artifact path is too broad")

        for pattern in RISKY_LOG_PATTERNS:
            if pattern.search(raw):
                fail(errors, f"{rel}: workflow contains a risky whole-environment/debug logging pattern")
                break

        for match in re.finditer(r"/home/([A-Za-z0-9._-]+)", raw):
            if match.group(1) not in ALLOWED_HOME_NAMES:
                fail(errors, f"{rel}: workflow contains private-looking home path {match.group(0)!r}")

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(f"PASS public workflow policy: {len(workflows)} workflows checked")
    return 0


def check_artifacts(directory: Path) -> int:
    errors: list[str] = []
    if not directory.is_dir():
        print(f"FAIL artifact directory does not exist: {directory}", file=sys.stderr)
        return 1

    checked = 0
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory)
        size = path.stat().st_size
        if size > MAX_PUBLIC_TEXT_ARTIFACT:
            fail(errors, f"{rel}: text/debug artifact is too large for public CI ({size} bytes)")
            continue
        data = path.read_bytes()
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        checked += 1

        for match in re.finditer(r"/home/([A-Za-z0-9._-]+)", text):
            if match.group(1) not in ALLOWED_HOME_NAMES:
                fail(errors, f"{rel}: contains private-looking home path {match.group(0)!r}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(errors, f"{rel}: contains secret-like material matching {pattern.pattern!r}")
                break

    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1

    print(f"PASS public artifact hygiene: {checked} text files checked")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    if args.artifact_dir is not None:
        return check_artifacts(args.artifact_dir)
    return check_workflows()


if __name__ == "__main__":
    raise SystemExit(main())
