-- SPDX-License-Identifier: GPL-3.0-only
-- Adapted for Maho Settings from Hyprbind at
-- b55e527b439ffd3f97d4d8c1102052095dcf7b9a.
-- Hyprbind Copyright (c) 2026 Mashrur Rahman Rawnok (NullifiedSec).
-- Original project: https://github.com/NullifiedSec/hyprbind
-- Used under the Hyprbind -> MahoOS Special License Exception v1.0.
--
-- Maho adaptation: the collector models hl.unbind() in execution order so the
-- generated user overlay can truthfully shadow immutable default keybinds.

-- Collect Hyprland keybinds by executing a config against a stubbed `hl` API.
-- Usage: lua collect_binds.lua /path/to/hyprland.lua

local config_path = assert(arg[1], "usage: collect_binds.lua <hyprland.lua>")
local config_dir = config_path:match("^(.*)/[^/]+$") or "."

package.path = table.concat({
  config_dir .. "/?.lua",
  config_dir .. "/?/init.lua",
  package.path,
}, ";")

-- The collector executes trusted Hyprland configuration to preserve Lua
-- control-flow semantics, but observation must never repeat external side
-- effects. Keep read-only file access for feature probes while blocking
-- process creation and filesystem mutation during collection.
local original_io_open = io.open
io.open = function(path, mode)
  mode = mode or "r"
  if mode:find("[wa+]") then
    return nil, "maho collector: write access is disabled"
  end
  return original_io_open(path, mode)
end
io.popen = function()
  return nil, "maho collector: subprocesses are disabled"
end
os.execute = function()
  return nil, "maho collector: subprocesses are disabled"
end
os.remove = function()
  return nil, "maho collector: filesystem mutation is disabled"
end
os.rename = function()
  return nil, "maho collector: filesystem mutation is disabled"
end

local function is_array(t)
  local n = 0
  for k in pairs(t) do
    if type(k) ~= "number" then
      return false
    end
    n = n + 1
  end
  return n == #t
end

local function json_escape(s)
  return (
    s:gsub("\\", "\\\\")
      :gsub('"', '\\"')
      :gsub("\n", "\\n")
      :gsub("\r", "\\r")
      :gsub("\t", "\\t")
  )
end

local function to_json(v)
  local ty = type(v)
  if ty == "nil" then
    return "null"
  elseif ty == "boolean" then
    return v and "true" or "false"
  elseif ty == "number" then
    return tostring(v)
  elseif ty == "string" then
    return '"' .. json_escape(v) .. '"'
  elseif ty == "table" then
    if is_array(v) then
      local parts = {}
      for i = 1, #v do
        parts[i] = to_json(v[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    local parts = {}
    for k, val in pairs(v) do
      parts[#parts + 1] = to_json(tostring(k)) .. ":" .. to_json(val)
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return '"' .. json_escape(tostring(v)) .. '"'
end

local function format_value(v, depth)
  depth = depth or 0
  if depth > 4 then
    return "…"
  end
  local ty = type(v)
  if ty == "nil" then
    return "nil"
  elseif ty == "boolean" or ty == "number" then
    return tostring(v)
  elseif ty == "string" then
    return string.format("%q", v)
  elseif ty == "function" then
    return "<function>"
  elseif ty == "table" then
    if v.__hyprbinds_handler then
      return tostring(v)
    end
    if is_array(v) then
      local parts = {}
      for i = 1, #v do
        parts[i] = format_value(v[i], depth + 1)
      end
      return "{ " .. table.concat(parts, ", ") .. " }"
    end
    local keys = {}
    for k in pairs(v) do
      keys[#keys + 1] = k
    end
    table.sort(keys, function(a, b)
      return tostring(a) < tostring(b)
    end)
    local parts = {}
    for _, k in ipairs(keys) do
      local key = type(k) == "string" and k:match("^[%a_][%w_]*$") and k or ("[" .. format_value(k, depth + 1) .. "]")
      parts[#parts + 1] = key .. " = " .. format_value(v[k], depth + 1)
    end
    return "{ " .. table.concat(parts, ", ") .. " }"
  end
  return tostring(v)
end

local function format_handler(handler)
  if type(handler) == "function" then
    return "<lua function>"
  end
  if type(handler) == "table" and handler.__hyprbinds_handler then
    return tostring(handler)
  end
  return format_value(handler)
end

local function command_from_handler(handler)
  if type(handler) ~= "table" or not handler.__hyprbinds_handler then
    return ""
  end
  if handler.path ~= "hl.dsp.exec_cmd" then
    return ""
  end
  if type(handler.args) ~= "table" or type(handler.args[1]) ~= "string" then
    return ""
  end
  return handler.args[1]
end

local function source_info(level)
  local info = debug.getinfo(level or 3, "Sl")
  if not info then
    return "", 0
  end
  local src = info.source or ""
  if src:sub(1, 1) == "@" then
    src = src:sub(2)
  end
  return src, info.currentline or 0
end

local function keybind_object()
  return {
    is_enabled = function()
      return true
    end,
    set_enabled = function() end,
    remove = function() end,
    unbind = function() end,
  }
end

local function rule_object()
  return {
    set_enabled = function() end,
    remove = function() end,
  }
end

local collected = {}
local collected_rules = {}
local collected_monitors = {}
local collected_workspace_rules = {}
local collected_layer_rules = {}
local collected_gestures = {}
local collected_devices = {}
local collected_curves = {}
local collected_animations = {}
local collected_env = {}
local collected_submaps = {}
local collected_startup = {}
local config_chunks = {}
local config_merged = {}
local submap_stack = { "" }
local event_context = "reload"

local RULE_META = { name = true, match = true, enabled = true }

local function deep_merge(dst, src)
  if type(src) ~= "table" then
    return src
  end
  if type(dst) ~= "table" then
    dst = {}
  end
  for k, v in pairs(src) do
    if type(v) == "table" and type(dst[k]) == "table" and not is_array(v) and not is_array(dst[k]) then
      dst[k] = deep_merge(dst[k], v)
    else
      dst[k] = v
    end
  end
  return dst
end

local function copy_table(t)
  if type(t) ~= "table" then
    return t
  end
  local out = {}
  for k, v in pairs(t) do
    if type(v) == "table" then
      out[k] = copy_table(v)
    else
      out[k] = v
    end
  end
  return out
end

local function collect_spec(list, spec, level)
  spec = type(spec) == "table" and spec or {}
  local file, line = source_info(level or 3)
  local fields = {}
  for k, v in pairs(spec) do
    fields[tostring(k)] = v
  end
  list[#list + 1] = {
    name = tostring(spec.name or ""),
    fields = fields,
    source_file = file,
    source_line = line,
  }
end

local function current_submap()
  return submap_stack[#submap_stack] or ""
end

local function collect_opts(opts)
  opts = opts or {}
  local flags = {}
  local description = opts.description or opts.desc or ""
  for _, name in ipairs({
    "locked",
    "release",
    "click",
    "drag",
    "long_press",
    "repeating",
    "non_consuming",
    "auto_consuming",
    "mouse",
    "transparent",
    "ignore_mods",
    "dont_inhibit",
    "submap_universal",
  }) do
    if opts[name] then
      flags[#flags + 1] = name
    end
  end
  if opts.device then
    flags[#flags + 1] = "device"
  end
  return flags, description
end

local function make_handler(path)
  local node = { __hyprbinds_handler = true, path = path }
  return setmetatable(node, {
    __index = function(_, key)
      return make_handler(path .. "." .. tostring(key))
    end,
    __call = function(_, ...)
      local args = { ... }
      local rendered = path
      if #args == 0 then
        rendered = path .. "()"
      elseif #args == 1 then
        rendered = path .. "(" .. format_value(args[1]) .. ")"
      else
        local parts = {}
        for i = 1, #args do
          parts[i] = format_value(args[i])
        end
        rendered = path .. "(" .. table.concat(parts, ", ") .. ")"
      end
      return setmetatable({
        __hyprbinds_handler = true,
        path = path,
        rendered = rendered,
        args = args,
      }, {
        __tostring = function(self)
          return self.rendered
        end,
        __index = function(_, key)
          return make_handler(path .. "." .. tostring(key))
        end,
        __call = function(_, ...)
          return make_handler(path)(...)
        end,
      })
    end,
    __tostring = function(self)
      return self.rendered or (self.path .. "()")
    end,
  })
end

local function noop() end

hl = {
  bind = function(keys, handler, opts)
    local flags, description = collect_opts(opts)
    local file, line = source_info(3)
    collected[#collected + 1] = {
      keys = tostring(keys),
      action = format_handler(handler),
      command = command_from_handler(handler),
      flags = flags,
      description = description,
      submap = current_submap(),
      source_file = file,
      source_line = line,
    }
    return keybind_object()
  end,
  unbind = function(keys)
    local chord = tostring(keys or "")
    local submap = current_submap()
    local kept = {}
    for _, bind in ipairs(collected) do
      if not (bind.keys == chord and bind.submap == submap) then
        kept[#kept + 1] = bind
      end
    end
    collected = kept
  end,
  define_submap = function(name, reset_or_fn, maybe_fn)
    local reset = ""
    local fn = reset_or_fn
    if type(reset_or_fn) == "string" then
      reset = reset_or_fn
      fn = maybe_fn
    end
    if type(fn) ~= "function" then
      return
    end
    local file, line = source_info(3)
    local before = #collected
    submap_stack[#submap_stack + 1] = tostring(name)
    local ok, err = pcall(fn)
    submap_stack[#submap_stack] = nil
    collected_submaps[#collected_submaps + 1] = {
      name = tostring(name),
      reset = tostring(reset),
      source_file = file,
      source_line = line,
      bind_count = #collected - before,
    }
    if not ok then
      error(err, 0)
    end
  end,
  get_current_submap = function()
    return current_submap()
  end,
  dispatch = noop,
  exec_cmd = function(cmd, opts)
    local file, line = source_info(3)
    local command
    if type(cmd) == "string" then
      command = cmd
    else
      command = tostring(cmd or "")
    end
    local workspace = ""
    if type(opts) == "table" and opts.workspace ~= nil then
      workspace = tostring(opts.workspace)
    end
    collected_startup[#collected_startup + 1] = {
      command = command,
      when = event_context,
      workspace = workspace,
      source_file = file,
      source_line = line,
    }
  end,
  on = function(event, fn)
    if type(fn) ~= "function" then
      return
    end
    local ev = tostring(event or "")
    local prev = event_context
    local lower = string.lower(ev)
    if lower:find("shutdown", 1, true) then
      event_context = "shutdown"
    elseif lower:find("start", 1, true) then
      event_context = "start"
    else
      event_context = "event:" .. ev
    end
    local ok, err = pcall(fn)
    event_context = prev
    if not ok then
      error(err, 0)
    end
  end,
  env = function(name, value)
    local file, line = source_info(3)
    collected_env[#collected_env + 1] = {
      name = tostring(name or ""),
      value = tostring(value or ""),
      source_file = file,
      source_line = line,
    }
  end,
  config = function(t)
    if type(t) ~= "table" then
      return
    end
    config_chunks[#config_chunks + 1] = copy_table(t)
    config_merged = deep_merge(config_merged, t)
  end,
  monitor = function(spec)
    collect_spec(collected_monitors, spec, 4)
  end,
  device = function(spec)
    collect_spec(collected_devices, spec, 4)
  end,
  window_rule = function(spec)
    spec = type(spec) == "table" and spec or {}
    local file, line = source_info(3)
    local effects = {}
    for k, v in pairs(spec) do
      if not RULE_META[k] then
        effects[tostring(k)] = v
      end
    end
    local match = {}
    if type(spec.match) == "table" then
      for k, v in pairs(spec.match) do
        match[tostring(k)] = v
      end
    end
    collected_rules[#collected_rules + 1] = {
      name = tostring(spec.name or ""),
      match = match,
      effects = effects,
      enabled = spec.enabled,
      source_file = file,
      source_line = line,
    }
    return rule_object()
  end,
  workspace_rule = function(spec)
    collect_spec(collected_workspace_rules, spec, 4)
  end,
  layer_rule = function(spec)
    spec = type(spec) == "table" and spec or {}
    local file, line = source_info(3)
    local effects = {}
    for k, v in pairs(spec) do
      if not RULE_META[k] then
        effects[tostring(k)] = v
      end
    end
    local match = {}
    if type(spec.match) == "table" then
      for k, v in pairs(spec.match) do
        match[tostring(k)] = v
      end
    end
    collected_layer_rules[#collected_layer_rules + 1] = {
      name = tostring(spec.name or ""),
      match = match,
      effects = effects,
      enabled = spec.enabled,
      source_file = file,
      source_line = line,
    }
    return rule_object()
  end,
  permission = noop,
  curve = function(name, spec)
    spec = type(spec) == "table" and spec or {}
    local file, line = source_info(3)
    local fields = copy_table(spec)
    collected_curves[#collected_curves + 1] = {
      name = tostring(name or ""),
      fields = fields,
      source_file = file,
      source_line = line,
    }
  end,
  animation = function(spec)
    collect_spec(collected_animations, spec, 4)
  end,
  gesture = function(spec)
    collect_spec(collected_gestures, spec, 4)
  end,
  notify = noop,
  dsp = make_handler("hl.dsp"),
}

local scanned_files = {}
local variables = {}

local function remember_file(path)
  if type(path) ~= "string" or path == "" then
    return
  end
  if path:sub(1, 1) == "@" then
    path = path:sub(2)
  end
  if scanned_files[path] then
    return
  end
  scanned_files[path] = true
end

local function add_variable(name, value, file, line)
  if type(name) ~= "string" or name == "" then
    return
  end
  if type(value) ~= "string" then
    return
  end
  -- Prefer first definition; later duplicates keep the original.
  if variables[name] then
    return
  end
  variables[name] = {
    name = name,
    value = value,
    source_file = file or "",
    source_line = line or 0,
  }
end

local function scan_file_for_variables(path)
  local f = io.open(path, "r")
  if not f then
    return
  end
  local line_no = 0
  for line in f:lines() do
    line_no = line_no + 1
    -- Only explicit locals: local name = "value" / 'value'
    -- (avoids matching table fields like action = "workspace")
    local name, value = line:match("^%s*local%s+([%a_][%w_]*)%s*=%s*\"([^\"]*)\"")
    if not name then
      name, value = line:match("^%s*local%s+([%a_][%w_]*)%s*=%s*'([^']*)'")
    end
    if name and value then
      add_variable(name, value, path, line_no)
    end
  end
  f:close()
end

remember_file(config_path)

-- Hyprland-style require: keep Lua package semantics, but tolerate missing optional modules.
local original_require = require
function require(modname)
  local ok, result = pcall(original_require, modname)
  if ok then
    -- Resolve module file path for variable scanning.
    local resolved = package.searchpath(modname, package.path)
    if resolved then
      remember_file(resolved)
    end
    return result
  end
  -- Missing optional modules should not abort bind collection.
  if tostring(result):match("module ['\"]?.-['\"]? not found") then
    return nil
  end
  error(result, 0)
end

local chunk, load_err = loadfile(config_path)
if not chunk then
  io.stderr:write("failed to load config: " .. tostring(load_err) .. "\n")
  os.exit(1)
end

local ok, run_err = pcall(chunk)
local error_message = nil
if not ok then
  error_message = tostring(run_err)
  io.stderr:write("failed while executing config: " .. error_message .. "\n")
  -- Still emit whatever we collected before the failure.
end

for path in pairs(scanned_files) do
  scan_file_for_variables(path)
end

local variable_list = {}
for _, var in pairs(variables) do
  variable_list[#variable_list + 1] = var
end
table.sort(variable_list, function(a, b)
  return a.name < b.name
end)

local file_list = {}
for path in pairs(scanned_files) do
  file_list[#file_list + 1] = path
end
table.sort(file_list)

local payload = {
  config_path = config_path,
  config_dir = config_dir,
  binds = collected,
  window_rules = collected_rules,
  workspace_rules = collected_workspace_rules,
  layer_rules = collected_layer_rules,
  monitors = collected_monitors,
  devices = collected_devices,
  gestures = collected_gestures,
  curves = collected_curves,
  animations = collected_animations,
  env = collected_env,
  submaps = collected_submaps,
  startup = collected_startup,
  config_merged = config_merged,
  variables = variable_list,
  files = file_list,
}
if error_message then
  payload.error = error_message
end

io.write(to_json(payload))
io.write("\n")
