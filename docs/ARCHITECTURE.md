# Architecture

MahoOS keeps reading the system separate from changing the system.

That separation is the main rule behind the project. A component that notices a
problem does not automatically gain permission to repair anything it wants.

## Desktop

The visible desktop is built with Hyprland, Quickshell, and native Qt/QML
components.

Maho Edge, Link, Notify, Launcher, Files, Lock, Dock, Power, Clipboard, and the
wallpaper system share the same visual language and system state, but they do
not own arbitrary recovery actions.

## System state

Observers collect facts such as service health, session state, connectivity,
storage health, and security findings.

Guardian uses that evidence to decide whether the system is healthy, whether a
known recovery path is available, or whether the problem needs to be left for
the user.

Old or incomplete evidence is not treated as proof that the system is healthy.

## Recovery

Small failures stay with the component that already owns them. For example,
systemd can restart a crashed user service while Guardian checks that the new
process actually stays healthy.

Larger recovery actions use known providers with a clear target and a result
that can be checked afterward. Maho does not invent repair commands for an
unknown failure.

## Updates

System updates are built around a separate candidate root.

The candidate is updated and checked before it can replace the current system.
Recovery state is prepared first, and activation is kept separate from the
update itself.

Maho does not automatically reboot after preparing an update. The new system is
verified again after boot before it is considered healthy.

## Trust

Runtime state is not allowed to grant itself recovery authority.

Important system changes are tied to exact identities and expected effects.
When Maho cannot prove that a change is safe or that recovery succeeded, it
stops instead of guessing.

## V1 status boundary

The 2026-09-25 pre-installer architecture freeze records frozen design decisions,
not the current project gate. That historical gate was subsequently completed and
`v1-preinstaller-rc0` now exists.

Current V1 product work continues on installer + certified first boot, automatic
maintenance/update coordination, bad-update recovery closure, production
Prevention VM certification after the installer VM exists, fresh-install
reproducibility, and physical Signed Boot/hardware release gates. None of those
lanes weaken the fail-closed trust model described above.

For deeper implementation details, see
[Prevention Boundary](PREVENTION-BOUNDARY.md),
[Signed Boot Authority](SIGNED-BOOT-AUTHORITY.md), and the
[V1 pre-installer architecture freeze](V1-PREINSTALLER-ARCHITECTURE-FREEZE.md).
