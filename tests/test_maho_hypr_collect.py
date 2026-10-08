from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "lib" / "maho_hypr_collect.lua"


class CollectorContracts(unittest.TestCase):
    def collect(self, source: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "hyprland.lua"
            config.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                ["lua", str(COLLECTOR), str(config)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

    def test_unbind_removes_earlier_global_bind_before_override(self) -> None:
        state = self.collect(
            'hl.bind("SUPER + T", hl.dsp.exec_cmd("old"))\n'
            'hl.unbind("SUPER + T")\n'
            'hl.bind("SUPER + T", hl.dsp.exec_cmd("new"))\n'
        )
        rows = [row for row in state["binds"] if row["keys"] == "SUPER + T"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], 'hl.dsp.exec_cmd("new")')

    def test_unbind_is_scoped_to_current_submap(self) -> None:
        state = self.collect(
            'hl.bind("N", hl.dsp.exec_cmd("global"))\n'
            'hl.define_submap("media", function()\n'
            '  hl.bind("N", hl.dsp.exec_cmd("old-media"))\n'
            '  hl.unbind("N")\n'
            '  hl.bind("N", hl.dsp.exec_cmd("new-media"))\n'
            'end)\n'
        )
        global_rows = [
            row for row in state["binds"]
            if row["keys"] == "N" and row["submap"] == ""
        ]
        media_rows = [
            row for row in state["binds"]
            if row["keys"] == "N" and row["submap"] == "media"
        ]
        self.assertEqual(len(global_rows), 1)
        self.assertEqual(global_rows[0]["action"], 'hl.dsp.exec_cmd("global")')
        self.assertEqual(len(media_rows), 1)
        self.assertEqual(media_rows[0]["action"], 'hl.dsp.exec_cmd("new-media")')

    def test_source_location_is_preserved(self) -> None:
        state = self.collect(
            '-- first line\n'
            'hl.bind("SUPER + B", hl.dsp.exec_cmd("browser"), '
            '{ description = "Browser" })\n'
        )
        self.assertEqual(state["binds"][0]["source_line"], 2)
        self.assertTrue(state["binds"][0]["source_file"].endswith("hyprland.lua"))
        self.assertEqual(state["binds"][0]["description"], "Browser")


    def test_rules_motion_and_session_are_collected_with_source(self) -> None:
        state = self.collect(
            'hl.window_rule({ name = "float-test", match = { class = "test" }, float = true })\n'
            'hl.layer_rule({ name = "blur-shell", match = { namespace = "shell" }, blur = true })\n'
            'hl.workspace_rule({ workspace = "special:test", persistent = false })\n'
            'hl.curve("wind", { type = "bezier", points = { { 0.1, 0.2 }, { 0.3, 1.0 } } })\n'
            'hl.animation({ leaf = "windows", enabled = true, speed = 5, bezier = "wind" })\n'
            'hl.on("hyprland.start", function() hl.exec_cmd("agent") end)\n'
        )
        self.assertEqual(state["window_rules"][0]["effects"]["float"], True)
        self.assertEqual(state["window_rules"][0]["match"]["class"], "test")
        self.assertEqual(state["layer_rules"][0]["effects"]["blur"], True)
        self.assertEqual(state["workspace_rules"][0]["fields"]["workspace"], "special:test")
        self.assertTrue(state["workspace_rules"][0]["source_file"].endswith("hyprland.lua"))
        self.assertEqual(state["curves"][0]["name"], "wind")
        self.assertEqual(state["animations"][0]["fields"]["leaf"], "windows")
        self.assertEqual(state["startup"][0]["when"], "start")
        self.assertTrue(state["startup"][0]["source_file"].endswith("hyprland.lua"))

    def test_missing_optional_module_does_not_destroy_collection(self) -> None:
        state = self.collect(
            'require("definitely.not.present")\n'
            'hl.bind("SUPER + X", hl.dsp.exec_cmd("x"))\n'
        )
        self.assertNotIn("error", state)
        self.assertEqual(state["binds"][0]["keys"], "SUPER + X")

    def test_environment_and_local_variables_remain_distinct(self) -> None:
        state = self.collect(
            'local terminal = "kitty"\n'
            'hl.env("XCURSOR_SIZE", "24")\n'
        )
        self.assertEqual(state["variables"][0]["name"], "terminal")
        self.assertEqual(state["variables"][0]["value"], "kitty")
        self.assertEqual(state["env"][0]["name"], "XCURSOR_SIZE")
        self.assertEqual(state["env"][0]["value"], "24")


    def test_collection_blocks_external_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "hyprland.lua"
            marker_file = root / "must-not-exist"
            config.write_text(
                f'os.execute("touch {marker_file}")\n'
                f'local f = io.open("{marker_file}", "w")\n'
                'if f then f:write("bad"); f:close() end\n'
                'hl.bind("SUPER + S", hl.dsp.exec_cmd("safe"))\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["lua", str(COLLECTOR), str(config)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = json.loads(proc.stdout)
            self.assertFalse(marker_file.exists())
            self.assertEqual(state["binds"][0]["keys"], "SUPER + S")


if __name__ == "__main__":
    unittest.main()
