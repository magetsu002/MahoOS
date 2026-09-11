#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_system_restore_campaign as campaign  # noqa: E402
from maho_system_restore_journal import (  # noqa: E402
    create_journal,
    read_journal,
    transition_journal,
    write_journal,
)

TX = "l3-20260911T120000Z-deadbeef"
REV = "a" * 40
MID = "0123456789abcdef0123456789abcdef"
GID = "g3-0123456789abcdef01234567"
TARGET_UUID = "target-snapshot-uuid"
BACKUP_UUID = "backup-snapshot-uuid"
FSUUID = "ce979d1c-c145-4be0-9ce3-591b6fd0a3a1"
HOME_UUID = "home-subvolume-uuid"
KHASH = "1" * 64
IHASH = "2" * 64
