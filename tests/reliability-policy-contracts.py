#!/usr/bin/env python3
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
policy = json.loads((root / "config/platform.json").read_text())
boot = policy["boot"]
states = policy["system_states"]
assert boot["trusted_config_writer"] == "maho-signed-boot-publication"
assert boot["snapshot_integration"] == "recovery-input-only"
assert states["snapshot_retention_authority"] == "snapper-cleanup-policy"
assert states["recovery_eligibility_authority"] == "guardian"
assert states["boot_publication_authority"] == "maho-signed-boot-publication"
assert states["maximum_boot_candidates"] == 10
assert states["retained_snapshot_count_independent_of_boot_candidates"] is True

memory = policy["memory_pressure"]
assert memory["maximum_zram_mib"] == 8192
assert memory["user_slice_pressure_limit_percent"] == 85
zram = (root / "config/platform/zram-generator.conf").read_text()
pressure = (root / "config/platform/user-.slice-memory-pressure.conf").read_text()
shell = (root / "config/platform/maho-shell-memory-pressure.conf").read_text()
assert "min(ram / 2, 8192)" in zram
assert "ManagedOOMMemoryPressureLimit=85%" in pressure
assert "ManagedOOMPreference=avoid" in shell

installer = (root / "bin/maho-platform-install").read_text()
assert "sysctl-v1-candidate.conf" not in installer
print("ALL RELIABILITY POLICY CONTRACTS PASS")
