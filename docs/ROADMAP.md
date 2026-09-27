# Roadmap

MahoOS is still pre-V1. The priority now is proving that the system can update,
recover, reboot, and return to a known healthy state on real hardware.

## Working now

The desktop is usable as a daily environment.

Service recovery, system-generation recovery, kernel recovery, update
candidates, and destructive VM failure testing are already implemented.

The latest full-system torture campaign completed without a required scenario
ending in a known bug.

## Current focus

The production kernel update path completed its first transaction-backed physical
M4B certification on 2026-09-24. Future generations remain subject to the same
candidate, Admission, explicit-reboot, and postboot proof gates.

The historical pre-installer closure is complete. `v1-preinstaller-rc0` points
to `2d138aa930031f63b4c15a9234a11ce69a26f5e3`. That milestone closed the old
pre-installer gate; it did not complete the V1 product.

## Current V1 product requirements

The active V1 lanes are:

- installer + certified first boot
- automatic maintenance/update coordination
- bad-update recovery closure
- production Prevention VM certification after the installer VM exists
- fresh-install reproducibility
- physical Signed Boot/hardware release gates

These requirements continue to use the frozen fail-closed trust, generation,
recovery, and authority model. Historical pre-installer blockers are not carried
forward as current product blockers after they were closed.

## Before V1

V1 should be something that can be installed, updated, recovered, and trusted
without depending on the original development machine. Release packaging,
hardware coverage, and final documentation must converge around the active lanes
above rather than reopening the completed pre-installer gate.

## After V1

Later work can expand personalization, themes, recovery coverage, and support
for more hardware.
