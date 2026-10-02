#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lib" / "maho_settings_backend.py"
SPEC = importlib.util.spec_from_file_location("maho_settings_backend_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class SearchContracts(unittest.TestCase):
    def test_required_search_mappings_are_deterministic(self) -> None:
        cases = {
            "refresh": ("Displays / Refresh Rate", "displays", "displays"),
            "mic": ("Sound / Input", "sound", "sound"),
            "recovery": ("System / Recovery", "system", "recovery"),
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                result = settings.search(query)
                self.assertTrue(result)
                self.assertEqual(
                    (result[0]["label"], result[0]["route"], result[0]["target"]),
                    expected,
                )

    def test_search_contains_no_generated_or_remote_dependency(self) -> None:
        first = settings.search("refresh rate")
        second = settings.search("refresh rate")
        self.assertEqual(first, second)


class AdapterTruthContracts(unittest.TestCase):
    def test_sound_unavailable_is_reported_not_invented(self) -> None:
        with mock.patch.object(settings.shutil, "which", return_value=None):
            snapshot = settings.snapshot_sound()
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["outputs"], [])
        self.assertEqual(snapshot["inputs"], [])
        self.assertIn("unavailable", snapshot["error"].lower())

    def test_display_unavailable_is_reported_not_healthy(self) -> None:
        with mock.patch.object(settings, "hypr_json", return_value=(None, "no compositor")):
            snapshot = settings.snapshot_displays()
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["outputs"], [])
        self.assertEqual(snapshot["error"], "no compositor")

    def test_touchpad_classification_uses_compositor_device_identity(self) -> None:
        payload = {
            "keyboards": [{"name": "kbd"}],
            "mice": [{"name": "usb-mouse"}, {"name": "ELAN Touchpad"}],
        }
        with (
            mock.patch.object(settings, "hypr_json", return_value=(payload, "")),
            mock.patch.object(settings, "_input_current", return_value={}),
        ):
            snapshot = settings.snapshot_input()
        self.assertEqual(snapshot["mice"], ["usb-mouse"])
        self.assertEqual(snapshot["touchpads"], ["ELAN Touchpad"])

    def test_audio_parser_uses_real_wpctl_rows(self) -> None:
        fixture = """Audio
 ├─ Sinks:
 │  *   42. Built-in Audio Analog Stereo [vol: 0.50]
 │      77. USB Headset [vol: 0.20]
 ├─ Sources:
 │  *   55. USB Microphone [vol: 0.75]
"""
        outputs, inputs = settings._audio_rows(fixture)
        self.assertEqual(outputs[0], {"id": 42, "name": "Built-in Audio Analog Stereo", "default": True})
        self.assertEqual(outputs[1]["id"], 77)
        self.assertEqual(inputs[0], {"id": 55, "name": "USB Microphone", "default": True})

    def test_display_candidate_requires_advertised_mode(self) -> None:
        current = {
            "name": "DP-1",
            "modes": [
                {"resolution": "2560x1440", "refresh": 144.0},
                {"resolution": "1920x1080", "refresh": 60.0},
            ],
        }
        candidate, error = settings._validate_display_candidate(
            {
                "name": "DP-1",
                "resolution": "3840x2160",
                "refresh": 240.0,
                "scale": 1.0,
                "x": 0,
                "y": 0,
                "transform": 0,
            },
            current,
        )
        self.assertIsNone(candidate)
        self.assertIn("not advertised", error)


class PersistenceContracts(unittest.TestCase):
    def test_input_setting_persists_only_after_live_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "hypr", return_value=(0, "ok", "")),
            ):
                result = settings.input_set("disableWhileTyping", True)
            self.assertTrue(result["ok"])
            payload = json.loads(path.read_text())
            self.assertTrue(payload["values"]["disableWhileTyping"])

    def test_invalid_boolean_does_not_cross_action_boundary(self) -> None:
        with mock.patch.object(settings, "set_reduced_motion") as setter:
            result = settings.action("appearance.reducedMotion", {"enabled": "false"})
        self.assertFalse(result["ok"])
        setter.assert_not_called()


class DisplayRollbackContracts(unittest.TestCase):
    def test_revert_uses_exact_saved_baseline(self) -> None:
        token = "a" * 32
        baseline = [
            {
                "name": "eDP-1",
                "resolution": "2560x1600",
                "refresh": 240.0,
                "scale": 1.6,
                "x": 0,
                "y": 0,
                "transform": 0,
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory)
            transaction = {
                "version": 1,
                "token": token,
                "createdAt": 1.0,
                "baseline": baseline,
                "candidate": baseline[0],
                "status": "preview",
            }
            (tx_dir / f"{token}.json").write_text(json.dumps(transaction))
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings, "_apply_display_rows", return_value=(True, "")) as apply_rows,
            ):
                result = settings.display_revert(token)
            self.assertTrue(result["ok"])
            apply_rows.assert_called_once_with(baseline)
            self.assertTrue((tx_dir / f"{token}.revert").is_file())
            self.assertFalse((tx_dir / f"{token}.json").exists())

    def test_failed_revert_does_not_publish_success_marker(self) -> None:
        token = "b" * 32
        baseline = [{
            "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0,
        }]
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory)
            (tx_dir / f"{token}.json").write_text(json.dumps({
                "version": 1, "token": token, "createdAt": 1.0,
                "baseline": baseline, "candidate": baseline[0], "status": "preview",
            }))
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings, "_apply_display_rows", return_value=(False, "rejected")),
            ):
                result = settings.display_revert(token)
            self.assertFalse(result["ok"])
            self.assertFalse((tx_dir / f"{token}.revert").exists())
            self.assertTrue((tx_dir / f"{token}.json").exists())

    def test_watchdog_reverts_when_ui_never_confirms(self) -> None:
        token = "c" * 32
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory)
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings.time, "sleep"),
                mock.patch.object(settings, "display_revert", return_value={"ok": True}) as revert,
            ):
                rc = settings.display_watch(token)
            self.assertEqual(rc, 0)
            revert.assert_called_once_with(token, automatic=True)

    def test_session_display_apply_fails_back_to_preexisting_layout(self) -> None:
        persisted = [{
            "name": "eDP-1", "resolution": "1920x1200", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0,
        }]
        current = [{
            "name": "eDP-1", "resolution": "2560x1600", "refresh": 240.0,
            "scale": 1.6, "x": 0, "y": 0, "transform": 0,
        }]
        with (
            mock.patch.object(settings, "hypr_prefix", return_value=(["hyprctl"], "")),
            mock.patch.object(settings, "hypr", return_value=(0, "ok", "")),
            mock.patch.object(settings, "_apply_persisted_input", return_value=[]),
            mock.patch.object(settings, "_persisted_display_rows", return_value=persisted),
            mock.patch.object(settings, "_display_snapshot_rows", return_value=current),
            mock.patch.object(settings, "_apply_display_rows", side_effect=[(False, "bad mode"), (True, "")]) as apply_rows,
        ):
            result = settings.apply_session()
        self.assertIn("displays-apply-failed-rolled-back", result["skipped"])
        self.assertEqual(apply_rows.call_args_list[0].args[0], persisted)
        self.assertEqual(apply_rows.call_args_list[1].args[0], current)

    def test_topology_change_skips_persisted_arrangement(self) -> None:
        persisted = [{
            "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0,
        }]
        current = [{
            "name": "HDMI-A-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0,
        }]
        with (
            mock.patch.object(settings, "hypr_prefix", return_value=(["hyprctl"], "")),
            mock.patch.object(settings, "hypr", return_value=(0, "ok", "")),
            mock.patch.object(settings, "_apply_persisted_input", return_value=[]),
            mock.patch.object(settings, "_persisted_display_rows", return_value=persisted),
            mock.patch.object(settings, "_display_snapshot_rows", return_value=current),
            mock.patch.object(settings, "_apply_display_rows") as apply_rows,
        ):
            result = settings.apply_session()
        self.assertIn("displays-topology-changed", result["skipped"])
        apply_rows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
