-- managed-by: maho-setup session-v2
-- Own graphical Maho services only while this Hyprland session is alive.

hl.on("hyprland.start", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" start]])
end)

hl.on("hyprland.shutdown", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" stop]])
end)
