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
