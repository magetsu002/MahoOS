# V1 daily-driver reliability policy

This document records the source candidate policy. Installing the policy is an
explicit administrator action; it is not proof of physical-machine
certification.

## Boot and snapshots

Snapper owns retention and cleanup of filesystem recovery states. Guardian
decides which snapshots are eligible recovery inputs. Maho Signed Boot
publication is the sole writer of trusted current-epoch Limine configuration,
with at most ten published boot candidates. Snapshot count is intentionally
independent of boot-menu count.

`limine-snapper-sync` remains a recovery-input provider only. The installed
drop-in prevents it from starting after `/etc/maho/signed-boot-production` is
created by a future certified production publication transaction. Creating
that marker early is prohibited.

## Memory and storage

The platform policy provisions zstd zram at half of RAM capped at 8 GiB.
`systemd-oomd` monitors the user slice at 85% sustained pressure; the Maho shell
is marked `avoid` so ordinary applications remain preferable pressure victims.
This is graceful degradation, not a promise that arbitrary workloads cannot
exhaust memory.

A monthly, persistent Btrfs scrub runs at idle CPU/I/O priority. Its service
result, raw Btrfs device counters, and NVMe inventory are available through
`maho-storage-health`. SMART/NVMe attributes remain diagnostic and
device-specific; Maho does not turn a single vendor attribute into a
categorical disk-failure claim.

## Network and firewall

The regular unprivileged security observer covers current-user TCP listeners.
It does not cover UDP, every other user, or the complete host firewall, and its
JSON coverage object preserves those limits. “clean” therefore means clean
only within that declared scope.

The V1 source architecture selects **Maho-owned minimal host input filtering**.
`config/platform/maho-host-firewall.nft` owns only `table inet maho_host` and
an `input` base chain with a default-drop policy. It preserves loopback,
established/related flows, DHCP, required IPv6 control traffic, mDNS/LLMNR,
and ZeroTier UDP transport. It deliberately does not own `forward`, `output`,
provider-created tables, or expose SSH. The policy is not activated by the
current platform transaction; physical activation remains an explicit
administrator certification action.

Mullvad remains a VPN provider, not permanent MahoOS host-firewall authority.
Its daemon/tunnel state must be modeled independently, including disconnected
and lockdown states. ZeroTier is an overlay provider, not host-filter
authority. Neither silently substitutes for `inet maho_host`.

`maho-firewall-certify capture CONTEXT` reads the effective nftables ruleset
without changing it. Evidence distinguishes `protected`, `unprotected`,
`partial`, `insufficient-visibility`, `provider-conflict`, `unsupported`, and
`stale`. A successfully read empty ruleset is `unprotected`; a privilege or
netlink failure is `insufficient-visibility`. Status is complete only when all
four named contexts have fresh, decision-usable IPv4+IPv6 protected evidence.
Guardian must not translate missing, stale, unsupported, or
`insufficient-visibility` firewall evidence into a clean result.

Certification still requires separate captures for `normal-wifi`,
`mullvad-disconnected`, `mullvad-connected`, and `zerotier-active`. A
default-drop base chain proves a filtering baseline, not that every accepted
service, interface, overlay path, or provider rule is safe.

## Sysctl candidate

`config/platform/sysctl-v1-candidate.conf` is documentation and test input
only. The installer deliberately does not activate it. `kptr_restrict` and
redirect-rejection settings require physical compatibility checks with
NetworkManager, Mullvad, ZeroTier, IPv6, LAN access, and supported
container/libvirt workflows before activation.

## Physical certification still required

SDDM login/logout and PAM keyring cold-session behavior, real memory-pressure
workloads, actual scrub completion, all firewall contexts, Secure Boot NVIDIA
module trust, and production runtime deployment require a controlled physical
certification pass. No source-only test substitutes for those checks.
