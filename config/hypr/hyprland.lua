require("maho.core.windowing")
require("maho.core.input")
require("maho.appearance.decorations")
require("maho.core.binds")
require("maho.appearance.animations")
require("maho.core.session")

-- Maho Settings owns one mutable user overlay outside the immutable runtime.
-- Only ignore the module when it does not exist; syntax/runtime errors inside
-- an existing overlay must remain visible through Hyprland config health.
local maho_user_settings = package.searchpath("maho.user.settings", package.path)
if maho_user_settings ~= nil then
    require("maho.user.settings")
end
