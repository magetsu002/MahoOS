#!/usr/bin/env python3

REQUIRED_SCENARIOS = {
    "valid-chain": "TRUSTED",
    "recovery-loader": "TRUSTED-RECOVERY",
    "invalid-loader": "REFUSED",
    "wrong-signer": "REFUSED",
    "config-tamper": "REFUSED",
    "missing-config-enrollment": "UNTRUSTED",
    "kernel-tamper": "REFUSED",
    "initramfs-tamper": "REFUSED",
    "microcode-tamper": "REFUSED",
    "damaged-normal-recovery-available": "TRUSTED-RECOVERY",
    "damaged-recovery": "REFUSED",
    "old-generation-replay": "REPLAY-MODELED",
    "revoked-generation": "UNTRUSTED",
}
