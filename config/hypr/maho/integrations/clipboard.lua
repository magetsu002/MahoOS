-- Maho Clipboard hotkey integration.
--
-- Keep product bindings out of the user's general muscle-memory binds file so
-- Maho components can be installed or removed without overwriting local edits.
-- The permanent command is the authority; never bind to a repository checkout.

hl.bind(
    "SUPER + V",
    hl.dsp.exec_cmd([["$HOME/.local/bin/maho-clipboard"]])
)
