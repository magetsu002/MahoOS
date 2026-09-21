# Maho Prevention Boundary

## Security model

Maho prevention has three deliberately separate layers:

1. Intent Guard parses a small set of deterministic interactive shell effects for early feedback. Unknown syntax proceeds normally.
2. The BPF LSM boundary enforces actual filesystem and mount mutations by target inode, protected effect, operation, exact process start/executable identity, scope, and expiry. It never examines command names.
3. Guardian records denials as prevention evidence. A prevented mutation is not compromise evidence and does not by itself lower machine trust.

The canonical effect vocabulary comes from `guardian_admission.EffectKind`. Protected roots are projected once by `maho_prevention_kernel.enforcement_roots`; `/home` is not globally protected. Only the exact immutable Maho runtime subtree may be included there.

## Activation and boot behavior

The package installs the kernel object, loader, evidence recorder, system units, PolicyKit action, and tmpfiles rule. It does not enable the boundary automatically.

Activation attaches all hooks while enforcement is inactive, populates every required protected object, pins maps and links in bpffs, and only then switches enforcement on. A failed partial load remains inactive. Pinned links survive loader or policy-process exit. They do not survive reboot, so the system unit performs the same atomic load each boot. The evidence reader may restart independently without detaching enforcement.

The unit starts after local filesystems and before `multi-user.target`. This avoids enforcing against incomplete early-boot state while still covering the normal administrative/application environment. If activation fails at boot, systemd reports the unit failed; it does not pretend protection is active and it does not block the boot path. Once active in a boot, missing, stale, wrong-process, wrong-target, or expired authority fails closed with `EPERM`.

Physical activation is an explicit administrative step after the hostile VM campaign passes:

```text
sudo systemctl enable --now maho-prevention-boundary.service
sudo systemctl enable --now maho-prevention-evidence.service
```

Do not activate on a daily-driver host until its exact update, recovery, generation, boot-publication, and platform-install transactions project their verified parent authorities.

## Exact authority

Machine-local HMAC envelopes bind transaction, verified parent authority kind and identity, boot identity, PID start identity, executable digest/device/inode, effects, operations, target prefixes, source revision, generation, and expiry. The broker revalidates the live process before projecting exact target inodes into the kernel map. Root identity or an executable name is never sufficient.

High-level `WRITE` projects to both the write-open and truncate/setattr kernel hooks. Standalone metadata authority remains separate. Creation, unlink, rename, link, symlink, mount, and device operations remain separately scoped.

## Break glass

`maho-break-glass` requires an interactive exact-scope confirmation followed by fresh PolicyKit admin authentication. It authorizes one process, target, effect, and operation for at most five minutes, records a durable audit event, and never disables the global boundary. There is no `--force`, environment bypass, or persistent off switch.

## Platform findings

The verified development kernel exposes `CONFIG_BPF_LSM=y`, `CONFIG_BPF_SYSCALL=y`, BPF in the active LSM list, kernel BTF, bpffs, and libbpf 1.7. The hostile campaign boots this kernel in disposable QEMU and asks the kernel verifier to load the real object before running mutations. The workstation installation remains unactivated pending explicit administration.
