#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lib" / "maho_app_model.py"
spec = importlib.util.spec_from_file_location("maho_app_model", MODULE_PATH)
assert spec and spec.loader
app_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_model)


class MahoAppModelTests(unittest.TestCase):
    def write_desktop(self, root: Path, desktop_id: str, body: str) -> Path:
        applications = root / "applications"
        applications.mkdir(parents=True, exist_ok=True)
        path = applications / desktop_id
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[Desktop Entry]\nType=Application\n" + body, encoding="utf-8")
        return path

    def environment(self, data_home: Path, data_dirs: list[Path]):
        return mock.patch.dict(
            os.environ,
            {
                "XDG_DATA_HOME": str(data_home),
                "XDG_DATA_DIRS": ":".join(str(path) for path in data_dirs),
                "XDG_CURRENT_DESKTOP": "Hyprland",
                "LANG": "C",
            },
            clear=False,
        )

    def test_startup_wm_class_and_exec_create_canonical_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            empty = base / "empty"
            empty.mkdir()
            self.write_desktop(
                data,
                "com.visualstudio.code.desktop",
                "Name=Visual Studio Code\nStartupWMClass=Code\nExec=/usr/bin/code --unity-launch %F\nIcon=code\n",
            )

            with self.environment(data, [empty]):
                rows = app_model.discover_apps()

            self.assertEqual([row["id"] for row in rows], ["com.visualstudio.code.desktop"])
            aliases = set(rows[0]["aliases"])
            self.assertIn("code", aliases)
            self.assertIn("comvisualstudiocode", aliases)
            self.assertIn("visualstudiocode", aliases)

    def test_ambiguous_human_alias_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            empty = base / "empty"
            empty.mkdir()
            self.write_desktop(
                data,
                "com.alpha.Editor.desktop",
                "Name=Alpha Editor\nStartupWMClass=Code\nExec=/usr/bin/code %F\n",
            )
            self.write_desktop(
                data,
                "com.beta.Editor.desktop",
                "Name=Beta Editor\nStartupWMClass=Code\nExec=/usr/bin/beta-editor %F\n",
            )

            with self.environment(data, [empty]):
                rows = app_model.discover_apps()

            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertNotIn("code", set(row["aliases"]))
                self.assertTrue(row["id"].endswith(".desktop"))
            self.assertIn("comalphaeditor", set(rows[0]["aliases"]))
            self.assertIn("combetaeditor", set(rows[1]["aliases"]))

    def test_xdg_precedence_keeps_one_desktop_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user = base / "user"
            system = base / "system"
            self.write_desktop(user, "same.desktop", "Name=User Copy\nExec=true\n")
            self.write_desktop(system, "same.desktop", "Name=System Copy\nExec=true\n")

            with self.environment(user, [system]):
                rows = app_model.discover_apps()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "User Copy")
            self.assertEqual(rows[0]["id"], "same.desktop")

    def test_hidden_and_nodisplay_entries_are_not_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            empty = base / "empty"
            empty.mkdir()
            self.write_desktop(data, "visible.desktop", "Name=Visible\nExec=true\n")
            self.write_desktop(data, "hidden.desktop", "Name=Hidden\nHidden=true\nExec=true\n")
            self.write_desktop(data, "nodisplay.desktop", "Name=No Display\nNoDisplay=true\nExec=true\n")

            with self.environment(data, [empty]):
                rows = app_model.discover_apps()

            self.assertEqual([row["name"] for row in rows], ["Visible"])

    def test_launch_uses_exact_desktop_file_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            empty = base / "empty"
            empty.mkdir()
            desktop = self.write_desktop(data, "safe.desktop", "Name=Safe App\nExec=true\n")

            with self.environment(data, [empty]), \
                    mock.patch.object(app_model.shutil, "which", side_effect=lambda name: "/usr/bin/gio" if name == "gio" else None), \
                    mock.patch.object(app_model.subprocess, "Popen") as popen:
                result = app_model.launch_app("safe.desktop")

            self.assertEqual(result, 0)
            popen.assert_called_once()
            argv = popen.call_args.args[0]
            self.assertEqual(argv, ["gio", "launch", str(desktop)])
            self.assertNotIn("shell", popen.call_args.kwargs)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_identity_normalization_never_depends_on_window_title(self):
        self.assertEqual(app_model.normalize_identity("Code.desktop"), "code")
        self.assertEqual(app_model.normalize_identity("org.mozilla.firefox"), "orgmozillafirefox")
        self.assertNotIn("title", app_model._raw_identity_candidates({
            "id": "safe.desktop",
            "name": "Safe",
            "startupWmClass": "SafeClass",
            "exec": "/usr/bin/safe",
        }))


if __name__ == "__main__":
    unittest.main()
