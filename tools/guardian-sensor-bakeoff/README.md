# Guardian sensor bake-off

This directory is a research harness for choosing Guardian's kernel observation substrate.

It does **not** install, enable, or ship any candidate. Candidate releases are staged under a user cache, and privileged live capture is a separate explicit step.

## Candidates

- Cilium Tetragon 1.7.1
- Aqua Tracee 0.24.1
- Falco Security libs 0.26.0

Guardian owns evidence semantics, identity, proof strength, Maho authority/generation correlation, retention, and UX. The candidate only supplies raw observations.

## Selection rule

Pick the smallest upstream mechanism that gives Guardian trustworthy evidence for:

- process exec/exit and parentage
- stable process-instance identity
- process-attributed filesystem mutation
- process-attributed network activity
- service/cgroup context where available
- event-loss / coverage accounting
- bounded filtering and privacy controls
- low idle overhead on the daily driver

A candidate does not gain Maho mutation authority.
## Safety

`prepare.sh` only downloads/verifies upstream artifacts and clones Falco libs source. It never runs upstream install scripts.

`workload.py` creates a short-lived tree under `/tmp`, spawns a child and grandchild, performs file mutations, opens one loopback TCP connection, then removes its files.

No external network destination is contacted by the workload.

Do not run a candidate's privileged sensor through this harness until its exact command and cleanup behavior have been reviewed.

## Quick start

Stage and build candidates without privilege:

```bash
./tools/guardian-sensor-bakeoff/prepare.sh
```

Build the Falco modern-BPF examples before the live comparison:

```bash
cache="${XDG_CACHE_HOME:-$HOME/.cache}/maho/guardian-sensor-bakeoff"
cmake -S "$cache/candidates/falco-libs-0.26.0" \
  -B "$cache/build/falco-libs-0.26.0" \
  -DUSE_BUNDLED_DEPS=ON \
  -DBUILD_LIBSCAP_MODERN_BPF=ON \
  -DCREATE_TEST_TARGETS=OFF \
  -DBUILD_DRIVER=OFF \
  -DMODERN_BPFTOOL_EXE="$cache/candidates/tetragon-1.7.1/usr/local/lib/tetragon/bpftool" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$cache/build/falco-libs-0.26.0" --target scap-open sinsp-example -j8
```

Then run all privileged live captures behind **one** authorization boundary:

```bash
pkexec ./tools/guardian-sensor-bakeoff/run-live-bakeoff-root.sh
```

Do not wrap individual candidate commands in separate `pkexec` calls. The root runner exists specifically so one bake-off does not spam authentication prompts.

For manual non-privileged workload testing:

```bash
python tools/guardian-sensor-bakeoff/workload.py > /tmp/guardian-workload.json
```

After a candidate capture exists:

```bash
python tools/guardian-sensor-bakeoff/analyze.py \
  --candidate tetragon \
  --events /tmp/tetragon.jsonl \
  --manifest /tmp/guardian-workload.json
```

The analyzer is intentionally conservative. It reports what was present in captured evidence; it does not infer causality from timestamps.