-- MahoOS appearance layer.
-- These values currently preserve the known-good visual baseline.

hl.config({
    decoration = {
        rounding = 10,

        active_opacity = 1.0,
        inactive_opacity = 0.9,
        fullscreen_opacity = 1.0,

        blur = {
            enabled = true,
            size = 5,
            passes = 4,
            new_optimizations = true,
            ignore_opacity = true,
            xray = true,

            -- A wider Kawase footprint gives Maho glass real diffusion instead
            -- of merely showing a darkened copy of the application beneath it.
            -- Vibrancy is deliberately modest so wallpaper/window color survives
            -- the blur without turning saturated or neon.
            noise = 0.006,
            contrast = 0.93,
            brightness = 1.02,
            vibrancy = 0.24,
            vibrancy_darkness = 0.12,
        },

        shadow = {
            enabled = true,
            range = 10,
            render_power = 2,
            color = 0x33000000,
        },
    },
})

-- Maho Dock is a bounded layer surface, so blur can be scoped to the actual
-- material instead of using an invisible full-screen blur carrier. Keep xray
-- disabled: the compositor should diffuse what is physically behind the Dock,
-- allowing wallpaper/window color to influence the glass naturally.
if maho_dock_material_rule == nil then
    maho_dock_material_rule = hl.layer_rule({
        name = "maho-dock-material",
        match = { namespace = "maho-dock" },
        blur = true,
        ignore_alpha = 0.015,
        xray = false,
        order = 7,
    })
else
    maho_dock_material_rule:set_enabled(true)
end

-- Maho Link mirrors Notify's single-surface material model: only the
-- alpha-masked foreground card is blurred. The full-screen catcher uses a
-- separate namespace and can never participate in blur/damage history.
hl.layer_rule({
    name = "maho-link-material",
    match = { namespace = "maho-link" },
    blur = true,
    ignore_alpha = 0.16,
    xray = false,
    no_anim = true,
})




-- Maho Launcher: only the alpha-masked foreground card is blurred. The
-- full-screen catcher/dim plane uses maho-launcher-catcher and stays unblurred.
hl.layer_rule({
    name = "maho-launcher-material",
    match = { namespace = "maho-launcher" },
    blur = true,
    ignore_alpha = 0.16,
    xray = false,
    no_anim = true,
})

-- Maho Notify follows the same material model as Maho Clipboard: blur the
-- interactive layer itself and ignore transparent pixels. This keeps blur,
-- rounded geometry and drag motion in one compositor surface, eliminating
-- carrier/foreground drift while preserving a sharp foreground.
hl.layer_rule({
    name = "maho-notify-material",
    match = { namespace = "maho-notify-center" },
    blur = true,
    ignore_alpha = 0.16,
    xray = false,
    no_anim = true,
})

-- Transient and replayed notification cards use the same frosted material as
-- the center, but alpha masking keeps diffusion inside the rounded cards only.
hl.layer_rule({
    name = "maho-notify-popup-material",
    match = { namespace = "maho-notify-popup" },
    blur = true,
    ignore_alpha = 0.16,
    xray = false,
    no_anim = true,
})
