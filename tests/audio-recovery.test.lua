-- Exercise the actual status script through mpv's observed properties and events.
local script = assert(arg[1])
local selected = "pipewire/headphones"
local other = "pipewire/speakers"

local function player(initial_pause, output)
  local properties = { pause = initial_pause or false, ["audio-device"] = output or selected }
  local observers, events, messages, timers = {}, {}, {}, {}
  local clock, resumes = 0, 0
  local function notify(name, value)
    for _, callback in ipairs(observers[name] or {}) do callback(name, value) end
  end
  local function change(name, value)
    properties[name] = value
    notify(name, value)
  end
  package.loaded["mp"], package.loaded["mp.utils"] = nil, nil
  package.preload["mp"] = function()
    return {
      get_property = function(name, fallback) return properties[name] or fallback end,
      get_property_number = function(_, fallback) return fallback end,
      get_property_native = function(name) return properties[name] end,
      get_property_bool = function(name, fallback)
        if properties[name] ~= nil then return properties[name] end
        return fallback
      end,
      get_time = function() return clock end,
      set_property_bool = function(name, value)
        if name == "pause" and value == false then resumes = resumes + 1 end
        change(name, value)
      end,
      set_property_native = function(name, value) properties[name] = value end,
      set_property_number = function(name, value) properties[name] = value end,
      commandv = function(command, property)
        if command == "cycle" then change(property, not properties[property]) end
      end,
      add_timeout = function(delay, callback)
        local timer = { due = clock + delay, callback = callback, active = true }
        function timer:kill() self.active = false end
        timers[#timers + 1] = timer
        return timer
      end,
      observe_property = function(name, _, callback)
        observers[name] = observers[name] or {}
        table.insert(observers[name], callback)
      end,
      register_event = function(name, callback) events[name] = callback end,
      register_script_message = function(name, callback) messages[name] = callback end,
      add_hook = function() end
    }
  end
  package.preload["mp.utils"] = function()
    return { parse_json = function() return nil end, format_json = function() return "{}" end }
  end
  dofile(script)
  local api = {}
  function api.devices(...)
    local list = { { name = "auto" } }
    for _, name in ipairs({ ... }) do list[#list + 1] = { name = name } end
    change("audio-device-list", list)
  end
  function api.advance(seconds)
    clock = clock + seconds
    for _, timer in ipairs(timers) do
      if timer.active and timer.due <= clock then
        timer.active = false
        timer.callback()
      end
    end
  end
  function api.pause(value) change("pause", value) end
  function api.event(name, value) events[name](value) end
  function api.toggle() messages["radio-atlas-toggle"]() end
  function api.output(value) change("audio-device", value) end
  function api.check(paused, count)
    assert(properties.pause == paused, "unexpected pause state")
    assert(resumes == count, "unexpected number of automatic resumes: " .. resumes)
  end
  function api.loss(pause_first)
    -- mpv's property has already changed when the removal notification arrives;
    -- its pause observer runs afterward in the same event batch.
    properties.pause = true
    if pause_first then
      properties["audio-device-list"] = { { name = "auto" }, { name = other } }
      notify("pause", true)
      notify("audio-device-list", properties["audio-device-list"])
      return
    end
    api.devices(other)
    notify("pause", true)
  end
  api.devices(selected, other)
  notify("pause", properties.pause)
  api.event("file-loaded")
  return api
end

local p = player()
for cycle = 1, 3 do
  p.loss(cycle == 2)
  p.devices(other, "pipewire/unrelated")
  p.advance(1)
  p.check(true, cycle - 1)
  p.devices(selected, other)
  p.advance(0.21)
  p.check(false, cycle)
  p.advance(10)
  p.check(false, cycle)
end

-- Deliberate pauses, including direct MPRIS writes, never create a recovery.
for _, pause_kind in ipairs({ "initial", "mpris", "ui" }) do
  p = player(pause_kind == "initial")
  if pause_kind == "ui" then p.toggle() end
  if pause_kind == "mpris" then p.pause(true) end
  p.devices(selected, other, "pipewire/unrelated")
  p.advance(1)
  p.check(true, 0)
  p.devices(other)
  p.devices(selected, other)
  p.advance(1)
  p.check(true, 0)
end

-- Pause before removal, late after removal, or under System default is ambiguous.
p = player()
p.pause(true)
p.devices(other)
p.devices(selected, other)
p.advance(1)
p.check(true, 0)
p = player()
p.devices(other)
p.advance(1)
p.pause(true)
p.devices(selected, other)
p.advance(1)
p.check(true, 0)
p = player(false, "auto")
p.loss()
p.devices(selected, other)
p.advance(1)
p.check(true, 0)

-- Player actions cancel the one pending resume.
for _, cancel in ipairs({
  function(p) p.output(other) end,
  function(p) p.event("start-file"); p.event("file-loaded") end,
  function(p) p.event("end-file", { reason = "error", error = "failed" }) end,
  function(p) p.event("idle") end,
  function(p) p.event("shutdown") end,
  function(p) p.toggle(); p.pause(true) end,
  function(p) p.pause(false); p.pause(true) end
}) do
  p = player()
  p.loss()
  p.devices(selected, other)
  cancel(p)
  p.advance(1)
  p.check(true, 0)
end

-- Losing the selected device again during the delay prevents the resume.
p = player()
p.loss()
p.devices(selected, other)
p.devices(other)
p.advance(1)
p.check(true, 0)
print("Audio recovery tests passed")
