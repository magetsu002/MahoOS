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
 ├─ Devices:
 │      12. Audio Card [alsa]
 ├─ Sinks:
 │  *   42. Built-in Audio Analog Stereo [vol: 0.50]
 │      77. USB Headset [vol: 0.20]
 ├─ Sources:
 │      55. USB Microphone [vol: 0.75]
 ├─ Filters:
 │  *   88. Bluetooth Headset [Audio/Source]
 │      99. capture-internal [Stream/Input/Audio/Internal]
 └─ Streams:
       104. Firefox
Video
 ├─ Sources:
 │  *   86. Webcam
"""
        outputs, inputs = settings._audio_rows(fixture)
        self.assertEqual(outputs[0], {"id": 42, "name": "Built-in Audio Analog Stereo", "default": True})
        self.assertEqual(outputs[1]["id"], 77)
        self.assertEqual(inputs[0], {"id": 55, "name": "USB Microphone", "default": False})
        self.assertEqual(inputs[1], {"id": 88, "name": "Bluetooth Headset", "default": True})
        self.assertNotIn(99, [row["id"] for row in inputs])
        self.assertNotIn(104, [row["id"] for row in inputs])
        self.assertNotIn(86, [row["id"] for row in inputs])

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
                mock.patch.object(settings, "_hypr_set_input_option", return_value=(True, "")),
                mock.patch.object(settings, "hypr_option", return_value=True),
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


class DailyDriverMutationContracts(unittest.TestCase):
    def test_hypr_bool_option_is_truthful(self) -> None:
        with mock.patch.object(settings, "hypr_json", return_value=({"bool": True}, "")):
            self.assertIs(settings.hypr_option("input:left_handed", False), True)

    def test_last_active_display_cannot_be_disabled(self) -> None:
        snapshot = {
            "available": True,
            "enabledCount": 1,
            "outputs": [{
                "name": "eDP-1", "resolution": "2560x1600", "refresh": 240.0,
                "scale": 1.6, "x": 0, "y": 0, "transform": 0, "enabled": True,
                "modes": [{"resolution": "2560x1600", "refresh": 240.0}],
            }],
        }
        with (
            mock.patch.object(settings, "snapshot_displays", return_value=snapshot),
            mock.patch.object(settings.subprocess, "Popen") as popen,
        ):
            result = settings.display_preview({
                "name": "eDP-1", "resolution": "2560x1600", "refresh": 240,
                "scale": 1.6, "x": 0, "y": 0, "transform": 0, "enabled": False,
            })
        self.assertFalse(result["ok"])
        self.assertIn("last active", result["error"])
        popen.assert_not_called()

    def test_display_preview_watchdog_is_process_independent(self) -> None:
        snapshot = {
            "available": True,
            "enabledCount": 2,
            "outputs": [
                {
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
                {
                    "name": "DP-2", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 1920, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(settings, "TX_DIR", Path(directory)),
                mock.patch.object(settings, "snapshot_displays", return_value=snapshot),
                mock.patch.object(settings, "_apply_display_rows", return_value=(True, "")),
                mock.patch.object(settings.subprocess, "Popen") as popen,
            ):
                result = settings.display_preview({
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                })
        self.assertTrue(result["ok"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIs(popen.call_args.kwargs["stdin"], settings.subprocess.DEVNULL)

    def test_display_commit_rejects_topology_change_without_persisting(self) -> None:
        token = "d" * 32
        baseline = [{
            "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
        }]
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory) / "tx"
            tx_dir.mkdir()
            config = Path(directory) / "displays.json"
            (tx_dir / f"{token}.json").write_text(json.dumps({
                "version": 1, "token": token, "topology": ["DP-1"],
                "baseline": baseline, "proposed": baseline, "candidate": baseline[0],
            }))
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings, "DISPLAY_CONFIG", config),
                mock.patch.object(settings, "_display_snapshot_rows", return_value=[{
                    **baseline[0], "name": "HDMI-A-1",
                }]),
            ):
                result = settings.display_commit(token)
            self.assertFalse(result["ok"])
            self.assertIn("topology changed", result["error"])
            self.assertFalse(config.exists())

    def test_stale_audio_device_is_rejected(self) -> None:
        with (
            mock.patch.object(settings, "snapshot_sound", return_value={
                "available": True, "outputs": [{"id": 1}], "inputs": [],
            }),
            mock.patch.object(settings, "run") as runner,
        ):
            result = settings.sound_default("output", 99)
        self.assertFalse(result["ok"])
        runner.assert_not_called()

    def test_acceleration_profile_rejects_unknown_value(self) -> None:
        with mock.patch.object(settings, "hypr") as hypr:
            result = settings.input_set("accelProfile", "magic")
        self.assertFalse(result["ok"])
        hypr.assert_not_called()

    def test_notification_dnd_requires_confirmation(self) -> None:
        with (
            mock.patch.object(settings, "root_command", return_value="/bin/maho-notify"),
            mock.patch.object(settings, "run", return_value=(0, "on", "")),
            mock.patch.object(settings, "snapshot_notifications", return_value={
                "available": True, "dnd": False,
            }),
        ):
            result = settings.notification_dnd(True)
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"].lower())

    def test_region_timezone_rejects_unknown_zone_before_mutation(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/timedatectl"),
            mock.patch.object(settings, "_command_list", return_value=["Asia/Dubai"]),
            mock.patch.object(settings, "run") as runner,
        ):
            result = settings.region_timezone("Mars/Olympus")
        self.assertFalse(result["ok"])
        runner.assert_not_called()

    def test_default_app_rejects_non_candidate_before_mutation(self) -> None:
        entries = {
            "browser.desktop": {
                "id": "browser.desktop", "name": "Browser", "hidden": False,
                "noDisplay": False, "mimes": ["text/html"], "categories": [],
            },
        }
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/xdg-mime"),
            mock.patch.object(settings, "_application_entries", return_value=entries),
            mock.patch.object(settings, "run") as runner,
        ):
            result = settings.application_default("browser", "fake.desktop")
        self.assertFalse(result["ok"])
        runner.assert_not_called()

    def test_power_profile_missing_backend_is_rejected(self) -> None:
        with mock.patch.object(settings, "_power_profiles", return_value=(False, "", [], "missing")):
            result = settings.power_profile("balanced")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing")


    def test_display_failed_preview_restores_exact_baseline(self) -> None:
        snapshot = {
            "available": True,
            "enabledCount": 2,
            "outputs": [
                {
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
                {
                    "name": "DP-2", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 1920, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
            ],
        }
        baseline = settings._rows_from_display_snapshot(snapshot)
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(settings, "TX_DIR", Path(directory)),
                mock.patch.object(settings, "snapshot_displays", return_value=snapshot),
                mock.patch.object(
                    settings, "_apply_display_rows",
                    side_effect=[(False, "rejected"), (True, "")],
                ) as apply_rows,
                mock.patch.object(settings.subprocess, "Popen") as popen,
            ):
                result = settings.display_preview({
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                })
        self.assertFalse(result["ok"])
        self.assertEqual(apply_rows.call_args_list[1].args[0], baseline)
        popen.assert_not_called()

    def test_display_commit_rejects_candidate_drift_without_persisting(self) -> None:
        token = "e" * 32
        candidate = {
            "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory) / "tx"
            tx_dir.mkdir()
            config = Path(directory) / "displays.json"
            (tx_dir / f"{token}.json").write_text(json.dumps({
                "version": 1, "token": token, "topology": ["DP-1"],
                "baseline": [candidate], "proposed": [candidate], "candidate": candidate,
            }))
            drifted = [{**candidate, "refresh": 144.0}]
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings, "DISPLAY_CONFIG", config),
                mock.patch.object(settings, "_display_snapshot_rows", return_value=drifted),
            ):
                result = settings.display_commit(token)
        self.assertFalse(result["ok"])
        self.assertIn("no longer matches", result["error"])
        self.assertFalse(config.exists())

    def test_sound_default_success_uses_live_device_identity(self) -> None:
        with (
            mock.patch.object(settings, "snapshot_sound", side_effect=[
                {"available": True, "outputs": [{"id": 42, "default": False}], "inputs": []},
                {"available": True, "outputs": [{"id": 42, "default": True}], "inputs": []},
            ]),
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/wpctl"),
            mock.patch.object(settings, "run", return_value=(0, "", "")) as runner,
        ):
            result = settings.sound_default("output", 42)
        self.assertTrue(result["ok"])
        runner.assert_called_once_with(["/usr/bin/wpctl", "set-default", "42"])

    def test_sound_volume_missing_backend_fails_closed(self) -> None:
        with mock.patch.object(settings.shutil, "which", return_value=None):
            result = settings.sound_volume("output", 50)
        self.assertFalse(result["ok"])
        self.assertIn("unavailable", result["error"])

    def test_sound_volume_success_requires_readback(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/wpctl"),
            mock.patch.object(settings, "_default_audio_state", side_effect=[
                {"available": True, "volume": 20, "muted": False, "error": ""},
                {"available": True, "volume": 35, "muted": False, "error": ""},
            ]),
            mock.patch.object(settings, "run", return_value=(0, "", "")) as runner,
        ):
            result = settings.sound_volume("output", 35)
        self.assertTrue(result["ok"])
        runner.assert_called_once_with(
            ["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.350"]
        )

    def test_sound_mute_success_requires_readback(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/wpctl"),
            mock.patch.object(settings, "_default_audio_state", side_effect=[
                {"available": True, "volume": 35, "muted": False, "error": ""},
                {"available": True, "volume": 35, "muted": True, "error": ""},
            ]),
            mock.patch.object(settings, "run", return_value=(0, "", "")) as runner,
        ):
            result = settings.sound_mute("output", True)
        self.assertTrue(result["ok"])
        runner.assert_called_once_with(
            ["/usr/bin/wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"]
        )

    def test_sound_volume_failed_readback_does_not_claim_success(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/wpctl"),
            mock.patch.object(settings, "_default_audio_state", side_effect=[
                {"available": True, "volume": 20, "muted": False, "error": ""},
                {"available": True, "volume": 20, "muted": False, "error": ""},
            ]),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
        ):
            result = settings.sound_volume("output", 35)
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"].lower())

    def test_sound_mute_rejects_invalid_direction_before_command(self) -> None:
        with mock.patch.object(settings, "run") as runner:
            result = settings.sound_mute("sideways", True)
        self.assertFalse(result["ok"])
        runner.assert_not_called()

    def test_input_rejected_live_apply_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "hypr", return_value=(1, "", "rejected")),
            ):
                result = settings.input_set("leftHanded", True)
        self.assertFalse(result["ok"])
        self.assertFalse(path.exists())

    def test_acceleration_profile_persists_after_live_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "_hypr_set_input_option", return_value=(True, "")),
                mock.patch.object(settings, "hypr_option", return_value="flat"),
            ):
                result = settings.input_set("accelProfile", "flat")
            self.assertTrue(result["ok"])
            self.assertEqual(json.loads(path.read_text())["values"]["accelProfile"], "flat")

    def test_keyboard_layout_persists_after_live_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "_hypr_set_input_option", return_value=(True, "")),
                mock.patch.object(settings, "hypr_option", return_value="us"),
            ):
                result = settings.input_set("keyboardLayout", "us")
            self.assertTrue(result["ok"])
            self.assertEqual(json.loads(path.read_text())["values"]["keyboardLayout"], "us")

    def test_notification_enabled_success_requires_owner_round_trip(self) -> None:
        with (
            mock.patch.object(settings, "root_command", return_value="/bin/maho-notify"),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
            mock.patch.object(settings, "snapshot_notifications", return_value={
                "available": True, "active": True,
            }),
        ):
            result = settings.notification_enabled(True)
        self.assertTrue(result["ok"])

    def test_notification_enabled_failed_confirmation_is_not_success(self) -> None:
        with (
            mock.patch.object(settings, "root_command", return_value="/bin/maho-notify"),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
            mock.patch.object(settings, "snapshot_notifications", return_value={
                "available": True, "active": False,
            }),
        ):
            result = settings.notification_enabled(True)
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"].lower())

    def test_notification_dnd_success_requires_owner_round_trip(self) -> None:
        with (
            mock.patch.object(settings, "root_command", return_value="/bin/maho-notify"),
            mock.patch.object(settings, "run", return_value=(0, "on", "")),
            mock.patch.object(settings, "snapshot_notifications", return_value={
                "available": True, "dnd": True,
            }),
        ):
            result = settings.notification_dnd(True)
        self.assertTrue(result["ok"])

    def test_notification_clear_history_requires_empty_owner_state(self) -> None:
        with (
            mock.patch.object(settings, "root_command", return_value="/bin/maho-notify"),
            mock.patch.object(settings, "run", return_value=(0, "cleared", "")),
            mock.patch.object(settings, "snapshot_notifications", return_value={
                "available": True, "historyCount": 3,
            }),
        ):
            result = settings.notification_clear_history()
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"].lower())

    def test_region_timezone_success_is_verified(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/timedatectl"),
            mock.patch.object(settings, "_command_list", return_value=["Asia/Dubai"]),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
            mock.patch.object(settings, "_timedate_state", return_value=({"Timezone": "Asia/Dubai"}, "")),
        ):
            result = settings.region_timezone("Asia/Dubai")
        self.assertTrue(result["ok"])

    def test_region_automatic_time_success_is_verified(self) -> None:
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/timedatectl"),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
            mock.patch.object(settings, "_timedate_state", return_value=({"NTP": "yes"}, "")),
        ):
            result = settings.region_automatic_time(True)
        self.assertTrue(result["ok"])

    def test_region_locale_success_is_verified(self) -> None:
        def which(name: str):
            return f"/usr/bin/{name}"
        with (
            mock.patch.object(settings.shutil, "which", side_effect=which),
            mock.patch.object(settings, "_command_list", return_value=["en_US.utf8"]),
            mock.patch.object(settings, "run", return_value=(0, "", "")),
            mock.patch.object(settings, "_system_locale", return_value=("en_US.utf8", "")),
        ):
            result = settings.region_locale("en_US.utf8")
        self.assertTrue(result["ok"])

    def test_default_app_partial_failure_rolls_back_changed_mime(self) -> None:
        entries = {
            "browser.desktop": {
                "id": "browser.desktop", "name": "Browser", "hidden": False,
                "noDisplay": False,
                "mimes": ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"],
                "categories": [],
            },
        }
        defaults = {
            "x-scheme-handler/http": "old.desktop",
            "x-scheme-handler/https": "old.desktop",
            "text/html": "old.desktop",
        }
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/xdg-mime"),
            mock.patch.object(settings, "_application_entries", return_value=entries),
            mock.patch.object(settings, "_xdg_default", side_effect=lambda mime: defaults[mime]),
            mock.patch.object(
                settings, "run",
                side_effect=[(0, "", ""), (1, "", "rejected"), (0, "", "")],
            ) as runner,
        ):
            result = settings.application_default("browser", "browser.desktop")
        self.assertFalse(result["ok"])
        self.assertEqual(runner.call_count, 3)
        self.assertEqual(
            runner.call_args_list[-1].args[0],
            ["/usr/bin/xdg-mime", "default", "old.desktop", "x-scheme-handler/http"],
        )

    def test_power_profile_success_is_delegated(self) -> None:
        with (
            mock.patch.object(settings, "_power_profiles", side_effect=[
                (True, "balanced", ["balanced", "performance"], ""),
                (True, "performance", ["balanced", "performance"], ""),
            ]),
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/powerprofilesctl"),
            mock.patch.object(settings, "run", return_value=(0, "", "")) as runner,
        ):
            result = settings.power_profile("performance")
        self.assertTrue(result["ok"])
        runner.assert_called_once_with(
            ["/usr/bin/powerprofilesctl", "set", "performance"], timeout=5.0
        )


    def test_hypr_input_mutation_uses_lua_config(self) -> None:
        with mock.patch.object(settings, "hypr_eval", return_value=(True, "")) as evaluator:
            ok, error = settings._hypr_set_input_option("input:sensitivity", 0.25)
        self.assertTrue(ok)
        self.assertEqual(error, "")
        expression = evaluator.call_args.args[0]
        self.assertIn("hl.config", expression)
        self.assertIn("input = { sensitivity = 0.25 }", expression)
        self.assertNotIn("keyword", expression)

    def test_display_apply_uses_lua_monitor_and_enables_before_disables(self) -> None:
        rows = [
            {
                "name": "DP-OFF", "resolution": "1920x1080", "refresh": 60.0,
                "scale": 1.0, "x": 1920, "y": 0, "transform": 0, "enabled": False,
            },
            {
                "name": "DP-ON", "resolution": "1920x1080", "refresh": 60.0,
                "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
            },
        ]
        with mock.patch.object(settings, "hypr_eval", return_value=(True, "")) as evaluator:
            ok, error = settings._apply_display_rows(rows)
        self.assertTrue(ok)
        self.assertEqual(error, "")
        expressions = [call.args[0] for call in evaluator.call_args_list]
        self.assertIn('output = "DP-ON"', expressions[0])
        self.assertIn("hl.monitor", expressions[0])
        self.assertIn('output = "DP-OFF"', expressions[1])
        self.assertIn("disabled = true", expressions[1])

    def test_display_focus_uses_lua_dispatcher(self) -> None:
        with (
            mock.patch.object(settings, "snapshot_displays", side_effect=[
                {"available": True, "outputs": [{"name": "DP-1", "enabled": True, "focused": False}]},
                {"available": True, "outputs": [{"name": "DP-1", "enabled": True, "focused": True}]},
            ]),
            mock.patch.object(settings, "hypr_eval", return_value=(True, "")) as evaluator,
        ):
            result = settings.display_focus("DP-1")
        self.assertTrue(result["ok"])
        expression = evaluator.call_args.args[0]
        self.assertIn("hl.dispatch(hl.dsp.focus", expression)
        self.assertIn('monitor = "DP-1"', expression)

    def test_reduced_motion_uses_lua_config_before_persisting(self) -> None:
        with (
            mock.patch.object(settings, "_hypr_config", return_value=(True, "")) as config,
            mock.patch.object(settings, "intent_set") as persist,
        ):
            result = settings.set_reduced_motion(True)
        self.assertTrue(result["ok"])
        config.assert_called_once_with(("animations", "enabled"), False)
        persist.assert_called_once_with("appearance.reduced_motion", True)

    def test_touchpad_speed_rejects_stale_device(self) -> None:
        with (
            mock.patch.object(settings, "snapshot_input", return_value={
                "available": True, "touchpads": ["live-touchpad"],
            }),
            mock.patch.object(settings, "_hypr_set_device_input") as setter,
        ):
            result = settings.input_set("touchpadSensitivity", 0.2, "gone-touchpad")
        self.assertFalse(result["ok"])
        self.assertIn("no longer available", result["error"])
        setter.assert_not_called()

    def test_touchpad_speed_persists_by_device_after_live_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "snapshot_input", side_effect=[
                    {"available": True, "touchpads": ["pad-1"], "touchpadSpeeds": {"pad-1": 0.0}},
                    {"available": True, "touchpads": ["pad-1"], "touchpadSpeeds": {"pad-1": -0.35}},
                ]),
                mock.patch.object(settings, "_hypr_set_device_input", return_value=(True, "")),
            ):
                result = settings.input_set("touchpadSensitivity", -0.35, "pad-1")
            self.assertTrue(result["ok"])
            payload = json.loads(path.read_text())
            self.assertEqual(payload["devices"]["pad-1"]["sensitivity"], -0.35)

    def test_persisted_touchpad_speed_skips_stale_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({
                "version": 1,
                "values": {},
                "devices": {"gone-pad": {"sensitivity": 0.4}},
            }))
            with (
                mock.patch.object(settings, "INPUT_CONFIG", path),
                mock.patch.object(settings, "snapshot_input", return_value={
                    "available": True, "touchpads": ["live-pad"],
                }),
                mock.patch.object(settings, "_hypr_set_device_input") as setter,
            ):
                applied = settings._apply_persisted_input()
        self.assertEqual(applied, [])
        setter.assert_not_called()


    def test_display_preview_readback_failure_restores_baseline_and_spawns_no_watchdog(self) -> None:
        snapshot = {
            "available": True,
            "enabledCount": 2,
            "outputs": [
                {
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
                {
                    "name": "DP-2", "resolution": "1920x1080", "refresh": 60.0,
                    "scale": 1.0, "x": 1920, "y": 0, "transform": 0, "enabled": True,
                    "modes": [{"resolution": "1920x1080", "refresh": 60.0}],
                },
            ],
        }
        baseline = settings._rows_from_display_snapshot(snapshot)
        mismatched = [{**baseline[0], "refresh": 144.0}, baseline[1]]
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(settings, "TX_DIR", Path(directory)),
                mock.patch.object(settings, "snapshot_displays", return_value=snapshot),
                mock.patch.object(settings, "_apply_display_rows", return_value=(True, "")) as apply_rows,
                mock.patch.object(settings, "_display_snapshot_rows", side_effect=[mismatched, baseline]),
                mock.patch.object(settings.subprocess, "Popen") as popen,
            ):
                result = settings.display_preview({
                    "name": "DP-1", "resolution": "1920x1080", "refresh": 60,
                    "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
                })
        self.assertFalse(result["ok"])
        self.assertIn("did not apply", result["error"])
        self.assertGreaterEqual(apply_rows.call_count, 2)
        self.assertEqual(apply_rows.call_args_list[-1].args[0], baseline)
        popen.assert_not_called()

    def test_display_revert_readback_failure_does_not_publish_success_marker(self) -> None:
        token = "f" * 32
        baseline = [{
            "name": "DP-1", "resolution": "1920x1080", "refresh": 60.0,
            "scale": 1.0, "x": 0, "y": 0, "transform": 0, "enabled": True,
        }]
        with tempfile.TemporaryDirectory() as directory:
            tx_dir = Path(directory)
            (tx_dir / f"{token}.json").write_text(json.dumps({
                "version": 1, "token": token, "baseline": baseline,
                "proposed": baseline, "candidate": baseline[0],
            }))
            with (
                mock.patch.object(settings, "TX_DIR", tx_dir),
                mock.patch.object(settings, "_apply_display_rows", return_value=(True, "")),
                mock.patch.object(settings, "_display_snapshot_rows", return_value=[{
                    **baseline[0], "scale": 1.25,
                }]),
            ):
                result = settings.display_revert(token)
            self.assertFalse(result["ok"])
            self.assertFalse((tx_dir / f"{token}.revert").exists())
            self.assertTrue((tx_dir / f"{token}.json").exists())

    def test_mime_default_rejects_unsupported_mime_before_mutation(self) -> None:
        with mock.patch.object(settings, "run") as runner:
            result = settings.application_mime_default("application/x-maho-fake", "fake.desktop")
        self.assertFalse(result["ok"])
        runner.assert_not_called()

    def test_mime_default_verification_failure_rolls_back_previous_handler(self) -> None:
        entries = {
            "new.desktop": {
                "id": "new.desktop", "name": "New", "hidden": False,
                "noDisplay": False, "mimes": ["application/pdf"], "categories": [],
            },
        }
        with (
            mock.patch.object(settings.shutil, "which", return_value="/usr/bin/xdg-mime"),
            mock.patch.object(settings, "_application_entries", return_value=entries),
            mock.patch.object(settings, "_xdg_default", side_effect=["old.desktop", "other.desktop"]),
            mock.patch.object(settings, "run", side_effect=[(0, "", ""), (0, "", "")]) as runner,
        ):
            result = settings.application_mime_default("application/pdf", "new.desktop")
        self.assertFalse(result["ok"])
        self.assertIn("rolled back", result["error"])
        self.assertEqual(
            runner.call_args_list[-1].args[0],
            ["/usr/bin/xdg-mime", "default", "old.desktop", "application/pdf"],
        )



class NewPageTruthContracts(unittest.TestCase):
    def test_notify_missing_backend_is_unavailable(self) -> None:
        with mock.patch.object(settings, "root_command", return_value=None):
            state = settings.snapshot_notifications()
        self.assertFalse(state["available"])
        self.assertFalse(state["globalEnableSupported"])

    def test_applications_report_terminal_authority_absent(self) -> None:
        with (
            mock.patch.object(settings, "_application_entries", return_value={}),
            mock.patch.object(settings, "_autostart_entries", return_value=[]),
            mock.patch.object(settings, "_xdg_default", return_value=""),
            mock.patch.object(settings.shutil, "which", side_effect=lambda name: "/usr/bin/xdg-mime" if name == "xdg-mime" else None),
        ):
            state = settings.snapshot_applications()
        self.assertTrue(state["available"])
        self.assertFalse(state["terminalControlAvailable"])
        self.assertIn("authority", state["terminalError"])



if __name__ == "__main__":
    unittest.main()
