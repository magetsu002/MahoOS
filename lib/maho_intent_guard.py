#!/usr/bin/env python3
"""Structured, conservative UX guard for provable interactive mutations.

Unknown syntax is never called malicious.  This parser is an early UX layer;
the BPF LSM remains authoritative for every process and language.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shlex
from typing import Sequence

from maho_prevention_policy import MutationOperation
from maho_prevention_scope import ScopeMatch, TargetContext, classify_target


class IntentOutcome(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    BREAK_GLASS_REQUIRED = "BREAK_GLASS_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ParsedMutation:
    operation: MutationOperation
    target: str
    recursive: bool
    irreversible: bool
    source: str


@dataclass(frozen=True)
class IntentDecision:
    outcome: IntentOutcome
    reason: str
    mutation: ParsedMutation | None = None
    scope: ScopeMatch | None = None


@dataclass(frozen=True)
class ParsedShell:
    mutations: tuple[ParsedMutation, ...]
    incomplete: bool


_CONTROL = frozenset({"|", "||", "&&", ";", "&", "(", ")"})
_REDIRECT = frozenset({">", ">>", "1>", "1>>", "2>", "2>>"})


def _absolute(value: str, cwd: str) -> str | None:
    if not value or any(marker in value for marker in ("$", "`", "*", "?", "[", "]")):
        return None
    expanded = os.path.expanduser(value)
    return str(Path(expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)).resolve(strict=False))


def _commands(tokens: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in _CONTROL:
            if commands[-1]:
                commands.append([])
            continue
        commands[-1].append(token)
    return tuple(tuple(command) for command in commands if command)


def _rm(command: Sequence[str], cwd: str) -> list[ParsedMutation] | None:
    recursive = any(value in {"-r", "-R", "--recursive"} or value.startswith("-") and ("r" in value or "R" in value) for value in command[1:] if value != "--")
    targets: list[str] = []
    options = True
    for value in command[1:]:
        if options and value == "--":
            options = False
            continue
        if options and value.startswith("-"):
            continue
        target = _absolute(value, cwd)
        if target is None:
            return None
        targets.append(target)
    return [ParsedMutation(MutationOperation.UNLINK, target, recursive, True, "remove") for target in targets]


def _find(command: Sequence[str], cwd: str) -> list[ParsedMutation] | None:
    if "-delete" not in command:
        return []
    roots = []
    for value in command[1:]:
        if value.startswith("-") or value in {"!", "(", ")"}:
            break
        target = _absolute(value, cwd)
        if target is None:
            return None
        roots.append(target)
    return [ParsedMutation(MutationOperation.UNLINK, target, True, True, "find-delete") for target in roots]


def _dd(command: Sequence[str], cwd: str) -> list[ParsedMutation] | None:
    output = next((value[3:] for value in command[1:] if value.startswith("of=") and len(value) > 3), None)
    if output is None:
        return []
    target = _absolute(output, cwd)
    return None if target is None else [ParsedMutation(MutationOperation.DEVICE_WRITE, target, False, True, "device-output")]


def _mkfs(command: Sequence[str], cwd: str) -> list[ParsedMutation] | None:
    candidates = [value for value in command[1:] if not value.startswith("-")]
    if not candidates:
        return None
    target = _absolute(candidates[-1], cwd)
    return None if target is None else [ParsedMutation(MutationOperation.DEVICE_WRITE, target, False, True, "format-device")]


def _redirections(command: Sequence[str], cwd: str) -> list[ParsedMutation] | None:
    mutations: list[ParsedMutation] = []
    for index, token in enumerate(command[:-1]):
        if token not in _REDIRECT:
            continue
        target = _absolute(command[index + 1], cwd)
        if target is None:
            return None
        mutations.append(ParsedMutation(
            MutationOperation.WRITE, target, False, not token.endswith(">>"), "redirection",
        ))
    return mutations


def parse_shell_mutations(source: str, *, cwd: str) -> ParsedShell | None:
    try:
        lexer = shlex.shlex(source, posix=True, punctuation_chars="|&;()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = tuple(lexer)
    except ValueError:
        return None
    if not tokens:
        return ParsedShell((), False)
    mutations: list[ParsedMutation] = []
    incomplete = False
    for command in _commands(tokens):
        redirects = _redirections(command, cwd)
        if redirects is None:
            return None
        mutations.extend(redirects)
        words = tuple(value for value in command if value not in _REDIRECT)
        if not words:
            continue
        executable = os.path.basename(words[0])
        adapter = _rm if executable == "rm" else _find if executable == "find" else _dd if executable == "dd" else _mkfs if executable == "mkfs" or executable.startswith("mkfs.") else None
        if adapter is None:
            if not redirects:
                incomplete = True
            continue
        parsed = adapter(words, cwd)
        if parsed is None:
            return None
        mutations.extend(parsed)
    return ParsedShell(tuple(mutations), incomplete)


def assess_shell_intent(source: str, *, cwd: str, context: TargetContext = TargetContext()) -> IntentDecision:
    parsed = parse_shell_mutations(source, cwd=cwd)
    if parsed is None:
        return IntentDecision(IntentOutcome.UNKNOWN, "effect_not_proven")
    for mutation in parsed.mutations:
        scope = classify_target(mutation.target, context=context)
        if not scope.protected:
            continue
        if mutation.irreversible and scope.domain and scope.domain.value in {
            "root-filesystem", "boot-authority", "recovery-authority",
        }:
            return IntentDecision(IntentOutcome.BREAK_GLASS_REQUIRED, "provable_catastrophic_protected_mutation", mutation, scope)
        return IntentDecision(IntentOutcome.BLOCK, "provable_protected_mutation_requires_exact_authority", mutation, scope)
    if parsed.incomplete:
        return IntentDecision(IntentOutcome.UNKNOWN, "effect_not_proven")
    return IntentDecision(IntentOutcome.ALLOW, "no_protected_effect_proven")
