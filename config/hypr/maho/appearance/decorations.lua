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

-- Maho Link is a layer-shell surface, so ordinary window blur is not enough.
-- Keep the rule namespace-scoped: connectivity glass gets real compositor blur
-- without changing the material or performance characteristics of other layers.
hl.layer_rule({
    name = "maho-link-material",
    match = {
        namespace = "maho-link",
    },
    blur = true,
    ignore_alpha = 0.08,
    xray = false,
})
