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
