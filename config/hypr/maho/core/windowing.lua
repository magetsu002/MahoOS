-- MahoOS core window behavior.
-- Stable muscle-memory layer. Appearance systems must not own this.

hl.config({
    general = {
        gaps_in = 10,
        gaps_out = 20,
        border_size = 2,

        col = {
            active_border = "rgba(f0dedeff)",
            inactive_border = "rgba(ffb3b5ff)",
        },

        layout = "dwindle",
        resize_on_border = true,
        extend_border_grab_area = 15,
        hover_icon_on_border = true,
    },
})

-- QS Wallpaper Picker presentation.
hl.window_rule({
    name = "qs-wallpaper-picker",
    match = {
        title = "^(wallpaper-picker)$",
    },

    float = true,
    center = true,
    size = {
        "monitor_w * 0.82",
        "monitor_h * 0.45",
    },

    border_size = 0,
    rounding = 0,
    decorate = false,
    no_shadow = true,
    no_blur = true,
})

-- Maho Themes preserves the approved wallpaper carousel geometry while the
-- original picker remains available as the rollback surface.
hl.window_rule({
    name = "maho-themes",
    match = {
        title = "^(Maho Themes)$",
    },

    float = true,
    center = true,
    size = {
        "monitor_w * 0.82",
        "monitor_h * 0.45",
    },

    border_size = 0,
    rounding = 0,
    decorate = false,
    no_shadow = true,
    no_blur = true,
})
