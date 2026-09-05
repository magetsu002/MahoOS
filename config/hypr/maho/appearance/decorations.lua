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
            size = 3,
            passes = 4,
            new_optimizations = true,
            ignore_opacity = true,
            xray = true,
        },

        shadow = {
            enabled = true,
            range = 10,
            render_power = 2,
            color = 0x33000000,
        },
    },
})

-- Maho Link uses a dedicated, inputless Top-layer blur carrier. Do not blur
-- the interactive full-screen Overlay surface: its dim veil and translucent
-- Wi-Fi/Bluetooth card animate, and using that moving surface as Hyprland's
-- blur mask produces a visible second/ghost layer beneath the foreground.
hl.layer_rule({
    name = "maho-link-material",
    match = {
        namespace = "maho-link-backdrop",
    },
    blur = true,
    ignore_alpha = 0.001,
    xray = false,
})
