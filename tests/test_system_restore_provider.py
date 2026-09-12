#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_provider import (  # noqa: E402
    ProviderDialogue, ProviderProtocolError, _run_guarded_provider,
)

SID = 349
TXID = "l3-20260911T120000Z-deadbeef"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def expect_protocol_error(name: str, fn) -> None:
    try:
        fn()
    except ProviderProtocolError:
        print(f"PASS {name}")
        return
    raise AssertionError(name)


def ready_dialogue() -> ProviderDialogue:
    dialogue = ProviderDialogue(SID, TXID)
    response = dialogue.feed(
        f"Snapshot ID     : {SID}\nRestore snapshot {SID} (method: replace)?\nChoice [r/l/c]: "
    )
    check("exact target confirmation response is restore", response == ("r\n",))
    return dialogue


def run_fake_provider(source: str, *, timeout: float = 3.0):
    with tempfile.TemporaryDirectory(prefix="maho-provider-test-") as td:
        script = Path(td) / "provider.py"
        script.write_text(textwrap.dedent(source))
        return _run_guarded_provider(
            (sys.executable, str(script)),
            ProviderDialogue(SID, TXID),
            pre_mutation_timeout=timeout,
        )


def main() -> None:
    dialogue = ready_dialogue()
    backup = dialogue.feed("Description for backup subvolume @: ")
    check("provider backup is transaction-bound", backup == (f"Maho L3 backup {TXID}\n",))
    check("mutation has not started at backup prompt", not dialogue.mutation_started)

    check("mutation marker produces no input", dialogue.feed(f"Restoring snapshot {SID}...\n") == ())
    check("exact mutation boundary is recorded", dialogue.mutation_started)
    check(
        "successful provider reboot prompt is declined",
        dialogue.feed("Restore complete. Reboot now? [Y/n]: ") == ("n\n",),
    )
    check("provider reboot decline is recorded once", dialogue.final_reboot_declined)
    dialogue.finish(0)
    print("PASS successful exact-target dialogue is accepted")

    colored = ProviderDialogue(SID, TXID)
    result = colored.feed(
        f"\x1b[1;32mSnapshot ID     : \x1b[0m{SID}\r\nChoice [r/l/c]: "
    )
    check("ANSI provider output cannot hide exact identity", result == ("r\n",))

    expect_protocol_error(
        "unexpected snapshot identity is rejected",
        lambda: ProviderDialogue(SID, TXID).feed("Snapshot ID     : 348\nChoice [r/l/c]: "),
    )
    expect_protocol_error(
        "alternate snapshot selector is forbidden",
        lambda: ready_dialogue().feed("Select snapshot to restore (method: replace)\nChoice: "),
    )
    expect_protocol_error(
        "snapshot verification fallback is forbidden",
        lambda: ready_dialogue().feed("Select snapshot action\n[s] Select another snapshot\n[r] Restore anyway\n"),
    )

    no_identity = ProviderDialogue(SID, TXID)
    expect_protocol_error(
        "confirmation prompt without exact identity is rejected",
        lambda: no_identity.feed("Restore snapshot 349?\nChoice [r/l/c]: "),
    )

    early = ProviderDialogue(SID, TXID)
    expect_protocol_error(
        "mutation cannot begin before bounded dialogue",
        lambda: early.feed(f"Restoring snapshot {SID}...\n"),
    )
    expect_protocol_error(
        "reboot prompt cannot appear before mutation",
        lambda: ProviderDialogue(SID, TXID).feed("Restore complete. Reboot now? [Y/n]: "),
    )

    clean_cancel = ProviderDialogue(SID, TXID)
    clean_cancel.finish(1)
    print("PASS pre-mutation provider failure remains non-destructive")

    fake_success = ProviderDialogue(SID, TXID)
    expect_protocol_error(
        "zero exit before mutation cannot masquerade as restore success",
        lambda: fake_success.finish(0),
    )

    for bad in (0, -1):
        try:
            ProviderDialogue(bad, TXID)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid snapshot id must fail closed")
    print("PASS invalid expected snapshot identity fails closed")

    fake = run_fake_provider("""
        import sys
        print("Snapshot ID     : 349", flush=True)
        sys.stdout.write("Choice [r/l/c]: "); sys.stdout.flush()
        assert sys.stdin.readline().strip() == "r"
        sys.stdout.write("Description for backup subvolume @: "); sys.stdout.flush()
        assert sys.stdin.readline().strip() == "Maho L3 backup l3-20260911T120000Z-deadbeef"
        print("Restoring snapshot 349...", flush=True)
        print("Restoring matching kernel versions...", flush=True)
        sys.stdout.write("Restore complete. Reboot now? [Y/n]: "); sys.stdout.flush()
        assert sys.stdin.readline().strip() == "n"
    """)
    check("PTY runner completes exact-target provider flow", fake.returncode == 0 and fake.mutation_started)
    check("PTY runner declines provider auto-reboot", fake.output.count("Restore complete. Reboot now? [Y/n]:") == 1)

    expect_protocol_error(
        "PTY runner aborts provider verification fallback before mutation",
        lambda: run_fake_provider("""
            import sys, time
            print("Snapshot ID     : 349", flush=True)
            sys.stdout.write("Choice [r/l/c]: "); sys.stdout.flush()
            sys.stdin.readline()
            print("Select snapshot action", flush=True)
            print("[s] Select another snapshot", flush=True)
            print("[r] Restore anyway", flush=True)
            time.sleep(5)
        """),
    )

    expect_protocol_error(
        "PTY runner times out before mutation instead of guessing input",
        lambda: run_fake_provider("""
            import time
            print("Snapshot ID     : 349", flush=True)
            time.sleep(5)
        """, timeout=0.2),
    )

    print("ALL SYSTEM RESTORE PROVIDER DIALOGUE CONTRACTS PASS")


if __name__ == "__main__":
    main()
