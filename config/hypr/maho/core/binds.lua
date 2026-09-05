-- Maho OS stable muscle-memory bindings.

local mainMod = "SUPER"

-- Applications.
hl.bind(mainMod .. " + RETURN", hl.dsp.exec_cmd("kitty"))
hl.bind(mainMod .. " + B", hl.dsp.exec_cmd("firefox"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd([["$HOME/.local/bin/maho-files" run "$HOME"]]))

hl.bind(
    mainMod .. " + W",
    hl.dsp.exec_cmd([["$HOME/.local/bin/qs-wallpaper-picker"]])
)

-- Laptop media keys. On laptops the Fn layer normally reaches Hyprland as
-- XF86 keysyms rather than as a literal Fn+F-key chord. These bindings mutate
-- the real system services; Maho Shell observes those service changes and
-- raises its transient volume/brightness OSD automatically.
hl.bind(
    "XF86AudioRaiseVolume",
    hl.dsp.exec_cmd([[wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+]]),
    { repeating = true }
)

hl.bind(
    "XF86AudioLowerVolume",
    hl.dsp.exec_cmd([[wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-]]),
    { repeating = true }
)

hl.bind(
    "XF86AudioMute",
    hl.dsp.exec_cmd([[wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle]])
)

hl.bind(
    "XF86AudioMicMute",
    hl.dsp.exec_cmd([[wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle]])
)

hl.bind(
    "XF86MonBrightnessUp",
    hl.dsp.exec_cmd([[brightnessctl set 5%+]]),
    { repeating = true }
)

hl.bind(
    "XF86MonBrightnessDown",
    hl.dsp.exec_cmd([[brightnessctl set 5%-]]),
    { repeating = true }
)

-- Window basics.
hl.bind(mainMod .. " + Q", hl.dsp.window.close())

hl.bind(
    mainMod .. " + F",
    hl.dsp.window.fullscreen({
        mode = "fullscreen",
        action = "toggle",
    })
)

hl.bind(
    mainMod .. " + M",
    hl.dsp.window.fullscreen({
        mode = "maximized",
        action = "toggle",
    })
)

hl.bind(
    mainMod .. " + T",
    hl.dsp.window.float({ action = "toggle" })
)

-- Focus.
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Keyboard resizing.
hl.bind(
    mainMod .. " + SHIFT + right",
    hl.dsp.window.resize({ x = 100, y = 0, relative = true })
)

hl.bind(
    mainMod .. " + SHIFT + left",
    hl.dsp.window.resize({ x = -100, y = 0, relative = true })
)

hl.bind(
    mainMod .. " + SHIFT + down",
    hl.dsp.window.resize({ x = 0, y = 100, relative = true })
)

hl.bind(
    mainMod .. " + SHIFT + up",
    hl.dsp.window.resize({ x = 0, y = -100, relative = true })
)

-- Mouse move / resize.
hl.bind(
    mainMod .. " + mouse:272",
    hl.dsp.window.drag(),
    { mouse = true }
)

hl.bind(
    mainMod .. " + mouse:273",
    hl.dsp.window.resize(),
    { mouse = true }
)

-- Swap tiled windows.
hl.bind(
    mainMod .. " + ALT + left",
    hl.dsp.window.swap({ direction = "left" })
)

hl.bind(
    mainMod .. " + ALT + right",
    hl.dsp.window.swap({ direction = "right" })
)

hl.bind(
    mainMod .. " + ALT + up",
    hl.dsp.window.swap({ direction = "up" })
)

hl.bind(
    mainMod .. " + ALT + down",
    hl.dsp.window.swap({ direction = "down" })
)

-- Dwindle.
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"))
hl.bind(mainMod .. " + K", hl.dsp.layout("swapsplit"))

-- Groups.
hl.bind(mainMod .. " + G", hl.dsp.group.toggle())

-- Alt+Tab.
hl.bind(
    "ALT + Tab",
    function()
        hl.dispatch(hl.dsp.window.cycle_next())
        hl.dispatch(hl.dsp.window.alter_zorder({ mode = "top" }))
    end,
    { repeating = true }
)

-- Workspaces 1..10.
for i = 1, 10 do
    local key = tostring(i % 10)

    hl.bind(
        mainMod .. " + " .. key,
        hl.dsp.focus({ workspace = i })
    )

    hl.bind(
        mainMod .. " + SHIFT + " .. key,
        hl.dsp.window.move({
            workspace = i,
            follow = true,
        })
    )
end

hl.bind(
    mainMod .. " + Tab",
    hl.dsp.focus({ workspace = "m+1" })
)

hl.bind(
    mainMod .. " + SHIFT + Tab",
    hl.dsp.focus({ workspace = "m-1" })
)

hl.bind(
    mainMod .. " + mouse_down",
    hl.dsp.focus({ workspace = "e+1" })
)

hl.bind(
    mainMod .. " + mouse_up",
    hl.dsp.focus({ workspace = "e-1" })
)

hl.bind(
    mainMod .. " + CTRL + down",
    hl.dsp.focus({ workspace = "empty" })
)

hl.bind(
    mainMod .. " + CTRL + R",
    hl.dsp.exec_cmd("hyprctl reload")
)
