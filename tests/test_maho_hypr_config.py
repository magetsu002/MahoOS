from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lib" / "maho_hypr_config.py"
SPEC = importlib.util.spec_from_file_location("maho_hypr_config_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
writer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = writer
SPEC.loader.exec_module(writer)


def test_paths(root: Path, *, loader: bool = True):
    config_home = root / "config"
    state_home = root / "state"
    loader_path = config_home / "hypr" / "hyprland.lua"
    loader_path.parent.mkdir(parents=True, exist_ok=True)
    if loader:
        loader_path.write_text(
            'local p = package.searchpath("maho.user.settings", package.path)\n'
            'if p ~= nil then require("maho.user.settings") end\n',
            encoding="utf-8",
        )
    else:
        loader_path.write_text('require("maho.core.binds")\n', encoding="utf-8")
    state_dir = state_home / "maho" / "settings" / "hypr-config"
    return writer.WriterPaths(
        loader=loader_path,
        config=config_home / "hypr" / "maho" / "user" / "settings.lua",
        model=config_home / "maho" / "settings" / "hypr-managed.json",
        state_dir=state_dir,
        backups=state_dir / "backups",
        receipt=state_dir / "last-write.json",
        lock=state_dir / "writer.lock",
    )


class RenderContracts(unittest.TestCase):
    def test_render_is_typed_and_escapes_user_strings(self) -> None:
        model, lua = writer.render_model({
            "version": 1,
            "unbinds": ["SUPER + Q"],
            "binds": [{
                "id": "demo",
                "keys": "SUPER + T",
                "command": 'printf "hello"; touch /tmp/not-executed',
                "description": 'Terminal "safe"',
                "flags": ["locked"],
            }],
            "curves": [{
                "name": "fast",
                "points": [[0.1, 0.8], [0.2, 1.0]],
            }],
            "animations": [{
                "leaf": "windows",
                "enabled": True,
                "speed": 6,
                "bezier": "fast",
                "style": "slide",
            }],
        })
        self.assertEqual(model["version"], 1)
        self.assertIn('hl.unbind("SUPER + Q")', lua)
        self.assertIn('hl.dsp.exec_cmd("printf \\"hello\\"; touch /tmp/not-executed")', lua)
        self.assertIn('description = "Terminal \\"safe\\""', lua)
        self.assertIn("locked = true", lua)
        self.assertIn('hl.curve("fast"', lua)
        self.assertIn("hl.animation(", lua)

    def test_unknown_top_level_key_is_rejected(self) -> None:
        with self.assertRaises(writer.ConfigWriteError):
            writer.normalize_model({"version": 1, "rawLua": "os.execute('no')"})

    def test_duplicate_variable_is_rejected(self) -> None:
        with self.assertRaises(writer.ConfigWriteError):
            writer.normalize_model({
                "version": 1,
                "variables": [
                    {"name": "mainMod", "value": "SUPER"},
                    {"name": "mainMod", "value": "ALT"},
                ],
            })

    def test_duplicate_bind_in_same_scope_is_rejected(self) -> None:
        with self.assertRaises(writer.ConfigWriteError):
            writer.normalize_model({
                "version": 1,
                "binds": [
                    {"keys": "SUPER + T", "command": "kitty"},
                    {"keys": "SUPER + T", "command": "foot"},
                ],
            })

    def test_rule_effect_cannot_override_writer_metadata(self) -> None:
        with self.assertRaises(writer.ConfigWriteError):
            writer.normalize_model({
                "version": 1,
                "windowRules": [{
                    "name": "bad",
                    "match": {"class": "^demo$"},
                    "effects": {"match": {"title": ".*"}, "float": True},
                }],
            })

    def test_none_optional_id_normalizes_to_empty_string(self) -> None:
        model = writer.normalize_model({
            "version": 1,
            "binds": [{"id": None, "keys": "SUPER + T", "command": "kitty"}],
        })
        self.assertEqual(model["binds"][0]["id"], "")

    def test_submap_bind_is_materialized_in_owned_block(self) -> None:
        _, lua = writer.render_model({
            "version": 1,
            "submaps": [{"name": "media", "reset": "SUPER + Escape"}],
            "binds": [{
                "id": "media-next",
                "keys": "N",
                "command": "playerctl next",
                "description": "Next track",
                "submap": "media",
            }],
        })
        self.assertIn('hl.define_submap("media", "SUPER + Escape", function()', lua)
        self.assertIn('  hl.bind("N", hl.dsp.exec_cmd("playerctl next")', lua)


class TransactionContracts(unittest.TestCase):
    def test_submap_unbind_is_materialized_inside_submap(self) -> None:
        model, rendered = writer.render_model({
            "version": 1,
            "unbinds": [{"keys": "N", "submap": "media"}],
        })
        self.assertEqual(
            model["unbinds"],
            [{"keys": "N", "submap": "media"}],
        )
        self.assertIn('hl.define_submap("media", function()', rendered)
        self.assertIn('  hl.unbind("N")', rendered)

    def test_syntax_check_compiles_without_executing_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generated.lua"
            source.write_text('error("must not execute")\n', encoding="utf-8")
            calls = []

            def runner(command, timeout):
                calls.append(tuple(command))
                self.assertEqual(command[:2], [mock.ANY, "-e"])
                self.assertEqual(len(command), 3)
                self.assertIn("loadfile", command[2])
                self.assertIn(str(source), command[2])
                return 0, "", ""

            with mock.patch.object(writer.shutil, "which", return_value="/usr/bin/lua"):
                writer._syntax_check(source, runner)
            self.assertEqual(len(calls), 1)

    def test_non_live_apply_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = test_paths(Path(directory))
            result = writer.apply_model(
                {"version": 1, "binds": [{
                    "id": "demo",
                    "keys": "SUPER + T",
                    "command": "kitty",
                    "description": "Terminal",
                }]},
                paths=paths,
                reload_live=False,
                settle_seconds=0,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["changed"])
            self.assertTrue(paths.config.is_file())
            self.assertTrue(paths.model.is_file())
            self.assertIn("hl.bind", paths.config.read_text(encoding="utf-8"))

            second = writer.apply_model(
                json.loads(paths.model.read_text(encoding="utf-8")),
                paths=paths,
                reload_live=False,
                settle_seconds=0,
            )
            self.assertTrue(second["ok"])
            self.assertFalse(second["changed"])

    def test_changed_write_creates_last_good_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = test_paths(Path(directory))
            first = {"version": 1, "environment": [{"name": "A", "value": "one"}]}
            second = {"version": 1, "environment": [{"name": "A", "value": "two"}]}
            writer.apply_model(first, paths=paths, reload_live=False, settle_seconds=0)
            before = paths.config.read_bytes()
            result = writer.apply_model(second, paths=paths, reload_live=False, settle_seconds=0)
            backup = Path(result["backup"])
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_bytes(), before)

    def test_live_apply_requires_installed_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = test_paths(Path(directory), loader=False)

            def runner(command, timeout):
                if command[-1] == "configerrors":
                    return 0, "", ""
                return 0, "ok", ""

            with self.assertRaises(writer.ConfigWriteError):
                writer.apply_model(
                    {"version": 1},
                    paths=paths,
                    hypr_prefix=["hyprctl"],
                    runner=runner,
                    reload_live=True,
                    settle_seconds=0,
                )
            self.assertFalse(paths.config.exists())

    def test_live_apply_verifies_reload_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = test_paths(Path(directory))
            calls = []

            def runner(command, timeout):
                calls.append(tuple(command))
                if command[-1] == "configerrors":
                    return 0, "", ""
                if command[-1] == "reload":
                    return 0, "ok", ""
                # Lua syntax probe.
                return 0, "", ""

            result = writer.apply_model(
                {"version": 1, "environment": [{"name": "MAHO_TEST", "value": "1"}]},
                paths=paths,
                hypr_prefix=["hyprctl", "-i", "test-instance"],
                runner=runner,
                reload_live=True,
                settle_seconds=0,
            )
            self.assertTrue(result["changed"])
            self.assertIn(("hyprctl", "-i", "test-instance", "reload"), calls)
            self.assertTrue(paths.receipt.is_file())

    def test_new_config_error_rolls_back_exact_previous_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = test_paths(Path(directory))
            writer.apply_model(
                {"version": 1, "environment": [{"name": "A", "value": "old"}]},
                paths=paths,
                reload_live=False,
                settle_seconds=0,
            )
            old_config = paths.config.read_bytes()
            old_model = paths.model.read_bytes()
            configerror_reads = 0

            def runner(command, timeout):
                nonlocal configerror_reads
                if command[-1] == "configerrors":
                    configerror_reads += 1
                    if configerror_reads == 1:
                        return 0, "", ""
                    if configerror_reads == 2:
                        return 0, "bad generated config", ""
                    return 0, "", ""
                if command[-1] == "reload":
                    return 0, "ok", ""
                return 0, "", ""

            with self.assertRaises(writer.ConfigWriteError):
                writer.apply_model(
                    {"version": 1, "environment": [{"name": "A", "value": "new"}]},
                    paths=paths,
                    hypr_prefix=["hyprctl"],
                    runner=runner,
                    reload_live=True,
                    settle_seconds=0,
                )
            self.assertEqual(paths.config.read_bytes(), old_config)
            self.assertEqual(paths.model.read_bytes(), old_model)
            self.assertGreaterEqual(configerror_reads, 3)

    def test_symlink_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = test_paths(root)
            target = root / "outside.lua"
            target.write_text("-- outside\n", encoding="utf-8")
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.symlink_to(target)
            with self.assertRaises(writer.ConfigWriteError):
                writer.apply_model(
                    {"version": 1},
                    paths=paths,
                    reload_live=False,
                    settle_seconds=0,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "-- outside\n")


if __name__ == "__main__":
    unittest.main()
