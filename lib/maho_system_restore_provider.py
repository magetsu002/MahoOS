#!/usr/bin/env python3
"""Fail-closed dialogue guard for the pinned L3 restore provider."""
from __future__ import annotations

from dataclasses import dataclass
import os
import pty
import re
import select
import signal
import subprocess
import time
from typing import Sequence

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TXID = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")


class ProviderProtocolError(RuntimeError):
    """Raised when upstream restore dialogue leaves Maho's bounded path."""


def _plain(text: str) -> str:
    return _ANSI.sub("", text).replace("\r", "")


@dataclass
class ProviderDialogue:
    expected_snapshot_id: int
    transaction_id: str
    confirmed: bool = False
    backup_named: bool = False
    mutation_started: bool = False
    final_reboot_declined: bool = False
    _seen: str = ""

    def __post_init__(self) -> None:
        if self.expected_snapshot_id <= 0:
            raise ValueError("expected snapshot id must be positive")
        if not _TXID.fullmatch(self.transaction_id):
            raise ValueError("invalid L3 transaction id")

    @property
    def backup_description(self) -> str:
        return f"Maho L3 backup {self.transaction_id}"

    def feed(self, output: str) -> tuple[str, ...]:
        """Consume provider output and return exact responses to write to its PTY."""
        self._seen += _plain(output)
        responses: list[str] = []

        if "Select snapshot to restore" in self._seen:
            raise ProviderProtocolError("provider attempted alternate snapshot selection")
        if "Select snapshot action" in self._seen:
            raise ProviderProtocolError("provider reported snapshot verification failure")
        if "Restore anyway" in self._seen:
            raise ProviderProtocolError("provider offered unsafe restore override")

        ids = re.findall(r"Snapshot ID\s*:\s*(\d+)", self._seen)
        if ids and any(int(value) != self.expected_snapshot_id for value in ids):
            raise ProviderProtocolError("provider presented an unexpected snapshot id")

        confirm_prompt = "Choice [r/l/c]:"
        if confirm_prompt in self._seen and not self.confirmed:
            if str(self.expected_snapshot_id) not in ids:
                raise ProviderProtocolError("provider confirmation lacked exact snapshot identity")
            self.confirmed = True
            responses.append("r\n")
            self._seen = self._seen.split(confirm_prompt, 1)[1]

        backup_prompt = "Description for backup subvolume"
        if backup_prompt in self._seen and not self.backup_named:
            if not self.confirmed:
                raise ProviderProtocolError("provider requested backup name before target confirmation")
            if ":" not in self._seen.split(backup_prompt, 1)[1]:
                return tuple(responses)
            self.backup_named = True
            responses.append(self.backup_description + "\n")
            self._seen = self._seen.split(backup_prompt, 1)[1]

        mutation_marker = f"Restoring snapshot {self.expected_snapshot_id}..."
        if mutation_marker in self._seen:
            if not self.confirmed or not self.backup_named:
                raise ProviderProtocolError("provider reached mutation before bounded dialogue completed")
            self.mutation_started = True

        reboot_prompt = "Restore complete. Reboot now? [Y/n]:"
        if reboot_prompt in self._seen and not self.final_reboot_declined:
            if not self.mutation_started:
                raise ProviderProtocolError("provider requested reboot before restore mutation")
            self.final_reboot_declined = True
            responses.append("n\n")
            self._seen = self._seen.split(reboot_prompt, 1)[1]

        return tuple(responses)

    def finish(self, returncode: int) -> None:
        """Validate that provider termination is consistent with an attempted restore."""
        if returncode == 0 and not self.mutation_started:
            raise ProviderProtocolError("provider exited successfully before restore mutation began")
        if self.mutation_started and not self.confirmed:
            raise ProviderProtocolError("restore mutation began without exact target confirmation")


PINNED_PROVIDER = ("/usr/bin/limine-snapper-restore",)


@dataclass(frozen=True)
class ProviderRunResult:
    returncode: int
    mutation_started: bool
    output: str


def _terminate_process_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)


def _run_guarded_provider(
    command: Sequence[str],
    dialogue: ProviderDialogue,
    *,
    pre_mutation_timeout: float = 30.0,
) -> ProviderRunResult:
    if not command:
        raise ValueError("provider command is required")
    master, slave = pty.openpty()
    started = time.monotonic()
    output_parts: list[str] = []
    proc = subprocess.Popen(
        list(command),
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    protocol_error: ProviderProtocolError | None = None
    try:
        while True:
            if not dialogue.mutation_started and time.monotonic() - started > pre_mutation_timeout:
                protocol_error = ProviderProtocolError("provider timed out before restore mutation")
                _terminate_process_group(proc)
                break

            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    output_parts.append(text)
                    if protocol_error is None:
                        try:
                            for response in dialogue.feed(text):
                                os.write(master, response.encode())
                        except ProviderProtocolError as exc:
                            protocol_error = exc
                            if not dialogue.mutation_started:
                                _terminate_process_group(proc)
                                break

            if proc.poll() is not None:
                break

        returncode = proc.wait()
        if protocol_error is not None:
            raise protocol_error
        dialogue.finish(returncode)
        joined = "".join(output_parts)
        if len(joined) > 1_000_000:
            joined = joined[-1_000_000:]
        return ProviderRunResult(
            returncode=returncode,
            mutation_started=dialogue.mutation_started,
            output=joined,
        )
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        if proc.poll() is None and not dialogue.mutation_started:
            _terminate_process_group(proc)


def run_pinned_provider(dialogue: ProviderDialogue) -> ProviderRunResult:
    """Run only the V1-pinned full-system restore wrapper."""
    return _run_guarded_provider(PINNED_PROVIDER, dialogue)
