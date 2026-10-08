#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_runtime_deployment import plan_deployment  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(("git", "-C", str(root), *args), text=True).strip()


def release(base: Path, revision: str, name: str) -> Path:
    target = base / name
    target.mkdir()
    (target / "manifest.json").write_text(json.dumps({"source_revision": revision}) + "\n")
    return target


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        repo = base / "repo"
        repo.mkdir()
        subprocess.run(("git", "init", "-q", str(repo)), check=True)
        git(repo, "config", "user.email", "test@maho.invalid")
        git(repo, "config", "user.name", "Maho Test")
        (repo / "payload").write_text("one\n")
        git(repo, "add", "payload")
        git(repo, "commit", "-qm", "one")
        old = git(repo, "rev-parse", "HEAD")

        plan = plan_deployment(repo, None)
        check("clean bootstrap is production eligible", plan.allowed and plan.trust_eligible and plan.transition == "bootstrap")

        (repo / "payload").write_text("two\n")
        dirty = plan_deployment(repo, None)
        check("dirty production source is rejected", not dirty.allowed and "source_checkout_dirty" in dirty.reasons)
        explicit = plan_deployment(repo, None, development=True)
        check("explicit dirty development runtime is marked trust-ineligible", explicit.allowed and explicit.source_dirty is True and not explicit.trust_eligible)

        git(repo, "add", "payload")
        git(repo, "commit", "-qm", "two")
        new = git(repo, "rev-parse", "HEAD")
        old_runtime = release(base, old, "old-runtime")
        new_runtime = release(base, new, "new-runtime")
        forward = plan_deployment(repo, old_runtime)
        check("clean descendant transition is admitted", forward.allowed and forward.transition == "fast-forward")

        composite_runtime = release(
            base,
            f"composite:base@{old}+feature@{new}",
            "composite-runtime",
        )
        composite_forward = plan_deployment(repo, composite_runtime)
        check(
            "clean commit containing every composite revision is production eligible",
            composite_forward.allowed
            and composite_forward.trust_eligible
            and composite_forward.transition == "composite-forward",
        )

        git(repo, "checkout", "-q", "-b", "side", old)
        (repo / "side").write_text("side\n")
        git(repo, "add", "side")
        git(repo, "commit", "-qm", "side")
        side = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", new)
        incomplete_composite = release(
            base,
            f"composite:base@{old}+side@{side}",
            "incomplete-composite-runtime",
        )
        incomplete = plan_deployment(repo, incomplete_composite)
        check(
            "candidate missing a composite revision remains unverifiable",
            not incomplete.allowed and incomplete.transition == "unrelated-or-unverifiable",
        )
        malformed_composite = release(
            base,
            f"composite:base@{old}+base@{new}",
            "malformed-composite-runtime",
        )
        malformed = plan_deployment(repo, malformed_composite)
        check(
            "malformed composite provenance remains unverifiable",
            not malformed.allowed and malformed.transition == "unrelated-or-unverifiable",
        )

        package_root = base / "package-root"
        (package_root / "share/maho").mkdir(parents=True)
        (package_root / "share/maho/release.json").write_text(
            json.dumps({"source_revision": new}) + "\n",
            encoding="utf-8",
        )
        previous_path = os.environ.get("PATH")
        os.environ["PATH"] = ""
        try:
            packaged_bootstrap = plan_deployment(package_root, None)
            packaged_transition = plan_deployment(package_root, old_runtime)
        finally:
            if previous_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous_path
        check(
            "packaged production source needs no Git client or object graph",
            packaged_bootstrap.allowed
            and packaged_bootstrap.trust_eligible
            and packaged_bootstrap.source_revision == new
            and packaged_bootstrap.source_dirty is None
            and packaged_bootstrap.transition == "bootstrap",
        )
        check(
            "packaged production transition is distribution-authorized",
            packaged_transition.allowed and packaged_transition.transition == "packaged-release",
        )

        git(repo, "checkout", "-q", old)
        downgrade = plan_deployment(repo, new_runtime)
        check("production downgrade is rejected", not downgrade.allowed and downgrade.transition == "downgrade")
        explicit_downgrade = plan_deployment(repo, new_runtime, development=True)
        check("explicit development downgrade is admitted but not trusted", explicit_downgrade.allowed and explicit_downgrade.transition == "downgrade" and not explicit_downgrade.trust_eligible)

        git(repo, "checkout", "-q", "--orphan", "unrelated")
        (repo / "payload").write_text("unrelated\n")
        git(repo, "add", "payload")
        git(repo, "commit", "-qm", "unrelated")
        divergent = plan_deployment(repo, new_runtime)
        check(
            "divergent production deployment is rejected",
            not divergent.allowed
            and divergent.transition == "unrelated-or-unverifiable"
            and "production_transition_unrelated-or-unverifiable" in divergent.reasons,
        )

    print("ALL MAHO RUNTIME DEPLOYMENT AUTHORITY TESTS PASS")


if __name__ == "__main__":
    main()
