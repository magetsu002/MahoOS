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

-- Maho Clipboard is a full-screen layer surface with a translucent bottom
-- sheet inside it. Blur only pixels above the low-alpha backdrop threshold so
-- the desktop remains crisp outside the sheet while the sheet receives real
-- compositor blur. QML owns the rise/fall motion, so compositor animation is
-- disabled for this namespace to avoid two animations fighting each other.
hl.layer_rule({
    name = "maho-clipboard-glass",
    match = {
        namespace = "maho-clipboard",
    },
    blur = true,
    ignore_alpha = 0.16,
    xray = false,
    no_anim = true,
})
