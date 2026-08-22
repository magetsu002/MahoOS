# Maho OS Theme Engine

M3 introduces the canonical Maho OS theme pipeline.

## Contract

Theme generation and theme consumption are separate.

A generator produces one canonical palette.

Consumers translate that palette into application-specific formats.

No consumer is allowed to independently derive colors from the wallpaper.

## Pipeline

wallpaper / source
→ generator
→ canonical palette
→ consumers
→ staged outputs
→ verification
→ activation

## Canonical palette

Runtime location:

`~/.cache/maho/theme/palette.json`

The palette is the only runtime color source of truth.

## M3 requirements

- deterministic palette generation
- explicit palette schema
- atomic writes
- staged rendering
- validation before activation
- consumer isolation
- rollback on failure
- manual fallback palette
- no modification of stable Maho core behavior

## Initial consumers

- Hyprland
- Kitty

Other consumers are added only after the core contract is proven.
