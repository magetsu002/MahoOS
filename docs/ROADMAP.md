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

The production kernel update path is going through physical certification.

A real update has already reached the offline candidate and initramfs stages.
The remaining work is to complete the candidate, approve it, activate it,
reboot into the new Primary kernel, and verify the result after boot.

## Before V1

MahoOS still needs a finished installer and ISO, physical signed-boot
certification, broader hardware testing, release packaging, and final
documentation cleanup.

V1 should be something that can be installed, updated, recovered, and trusted
without depending on the original development machine.

## After V1

Later work can expand personalization, themes, recovery coverage, and support
for more hardware.
