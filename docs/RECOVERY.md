# Recovery

Recovery is part of normal MahoOS behavior, not a separate emergency feature.

## Small failures

If a component already has a normal restart path, Maho lets that path do its
job.

For example, systemd can restart a crashed desktop service. Guardian then checks
whether the replacement actually stays healthy instead of assuming a restart
means the problem is solved.

## System updates

MahoOS is being built so updates happen in a separate candidate system before
they replace the system you are using.

The candidate is updated, checked, and tied to a recovery state first. A failed
candidate can be discarded without making it the live system.

Activation and reboot are separate steps. Maho does not automatically reboot
just because an update was prepared.

After reboot, the new system still has to prove that the expected root, kernel,
packages, boot files, home data, and recovery state are present before it is
treated as healthy.

## When Maho does not know

Maho does not try random repair commands when evidence is missing or the failure
is outside a known recovery path.

In that case it keeps the problem visible and waits for an explicit recovery or
user decision.

## Current status

The recovery model has extensive automated and disposable-VM testing.

The production kernel update and postboot verification path is still completing
physical certification before V1.
