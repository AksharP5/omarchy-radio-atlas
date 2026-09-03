local mp = require("mp")
local utils = require("mp.utils")

local status_path = os.getenv("RADIO_ATLAS_STATUS_FILE")
local queue_path = os.getenv("RADIO_ATLAS_QUEUE_FILE")
local queue = nil
local update_timer = nil
local last_volume = 70
local station_loaded = false
local max_queue_bytes = 4194304

local function clean_text(value, limit)
  if type(value) ~= "string" then return "" end
  value = value:gsub("[%c]", " "):gsub("  +", " ")
  if #value <= limit then return value end
  local last = limit
  while last > 0 do
    local next_byte = value:byte(last + 1)
    if not next_byte or next_byte < 128 or next_byte > 191 then break end
    last = last - 1
  end
  return value:sub(1, last)
end

local function empty_station()
  return { uuid = "", name = "", country = "", countryCode = "" }
end

local function status_station(station)
  if type(station) ~= "table" then return empty_station() end
  local latitude = type(station.latitude) == "number" and station.latitude or nil
  local longitude = type(station.longitude) == "number" and station.longitude or nil
  return {
    uuid = clean_text(station.uuid, 64),
    name = clean_text(station.name, 160),
    country = clean_text(station.country, 100),
    countryCode = clean_text(station.countryCode, 2),
    latitude = latitude,
    longitude = longitude
  }
end

local function read_queue()
  if queue then return queue end
  queue = {}
  if not queue_path then return queue end

  local file = io.open(queue_path, "r")
  if not file then return queue end
  local size = file:seek("end")
  if not size or size > max_queue_bytes then
    file:close()
    return queue
  end
  file:seek("set", 0)
  local parsed = utils.parse_json(file:read("*a"))
  file:close()
  if type(parsed) == "table" and #parsed <= 500 then queue = parsed end
  return queue
end

local function write_status(state)
  if not status_path then return end
  local temporary = status_path .. "." .. tostring(mp.get_property_number("pid", 0)) .. ".tmp"
  local file = io.open(temporary, "w")
  if not file then return end
  file:write(utils.format_json(state), "\n")
  file:close()
  os.rename(temporary, status_path)
end

local function current_status()
  local position = mp.get_property_number("playlist-pos", -1)
  local volume = mp.get_property_number("volume", last_volume)
  last_volume = math.floor(volume + 0.5)
  return {
    running = true,
    paused = mp.get_property_bool("pause", false),
    muted = mp.get_property_bool("mute", false),
    title = clean_text(mp.get_property("media-title", ""), 512),
    playlistPosition = position,
    playlistCount = mp.get_property_number("playlist-count", 0),
    volume = last_volume,
    loaded = station_loaded,
    station = status_station(read_queue()[position + 1])
  }
end

local function emit_status()
  update_timer = nil
  write_status(current_status())
end

local function schedule_update()
  if update_timer then update_timer:kill() end
  update_timer = mp.add_timeout(0.04, emit_status)
end

-- ---------------------------------------------------------------------------
-- Audio device recovery
--
-- When mpv's output device disappears (a USB interface unplugged, a dock
-- detached) mpv sets pause=true and never resumes, even once the device is
-- back. PipeWire reattaches the stream on its own; only mpv's paused flag is
-- left behind, so playback stays silent until somebody presses play.
--
-- Two things make that awkward to correct automatically:
--
--   1. mpv does not report *why* it paused. During a device loss current-ao,
--      audio-device, core-idle and eof-reached all read exactly as they do
--      after a deliberate pause, so the reason cannot be recovered from state.
--      radio-player therefore sends "radio-atlas-user-pause" before it toggles
--      pause, and any pause without that marker is treated as device loss.
--
--   2. There is no dependable way to tell when a device is ready again.
--      Enumeration takes anywhere from a moment to several seconds depending on
--      port, hub and device, and under --audio-device=auto mpv never reveals
--      which device it had resolved to, so a returning device cannot even be
--      recognised by name. Rather than guess a delay, recovery is
--      self-correcting: unpause and let mpv arbitrate. If the device is still
--      unusable mpv pauses again within moments, and that bounce is what drives
--      the backoff and retry below.
-- ---------------------------------------------------------------------------

local resume_settle_seconds = 1.0
local resume_debounce_seconds = 0.2
local max_resume_attempts = 8
local max_backoff_seconds = 8

local user_pause_pending = false
local user_pause_timer = nil
local device_lost = false
local known_devices = nil
local resume_timer = nil
local resume_attempts = 0
local resuming = false
local settle_timer = nil
local attempt_resume

local function clear_user_pause_marker()
  if user_pause_timer then user_pause_timer:kill() end
  user_pause_timer = nil
  user_pause_pending = false
end

-- radio-player announces a deliberate pause just before issuing it.
mp.register_script_message("radio-atlas-user-pause", function()
  if user_pause_timer then user_pause_timer:kill() end
  user_pause_pending = true
  -- The marker expires so a stale one cannot swallow a later device loss.
  user_pause_timer = mp.add_timeout(2, clear_user_pause_marker)
end)

local function cancel_resume()
  if resume_timer then resume_timer:kill() end
  if settle_timer then settle_timer:kill() end
  resume_timer = nil
  settle_timer = nil
  resuming = false
end

local function forget_device_loss()
  device_lost = false
  resume_attempts = 0
  cancel_resume()
end

-- Spread retries out as attempts accumulate: 0.5s, 1s, 2s, 4s, then 8s.
local function backoff_seconds()
  local delay = 0.5 * 2 ^ math.max(resume_attempts - 1, 0)
  if delay > max_backoff_seconds then delay = max_backoff_seconds end
  return delay
end

local function schedule_resume(delay)
  if resume_timer then resume_timer:kill() end
  resume_timer = mp.add_timeout(delay, attempt_resume)
end

-- Unpause and wait to see whether it holds. Success is decided by silence: if
-- mpv has not paused itself again once the settle window elapses, the device
-- really is back.
attempt_resume = function()
  resume_timer = nil
  if not device_lost then return end
  if resume_attempts >= max_resume_attempts then
    -- Out of attempts. Leave playback paused rather than retrying forever;
    -- the user can press play once the device is sorted out.
    forget_device_loss()
    schedule_update()
    return
  end

  resume_attempts = resume_attempts + 1
  resuming = true
  if settle_timer then settle_timer:kill() end
  settle_timer = mp.add_timeout(resume_settle_seconds, function()
    settle_timer = nil
    if resuming then
      resuming = false
      forget_device_loss()
      schedule_update()
    end
  end)
  mp.set_property_bool("pause", false)
end

mp.observe_property("pause", "native", function(_, value)
  if value == true then
    if user_pause_pending then
      -- Deliberate: radio-player told us this one was coming.
      clear_user_pause_marker()
      forget_device_loss()
    elseif resuming then
      -- Our unpause bounced straight back, so the device is not usable yet.
      resuming = false
      if settle_timer then settle_timer:kill() end
      settle_timer = nil
      schedule_resume(backoff_seconds())
    else
      -- Unmarked and unprompted: mpv lost its output device.
      device_lost = true
      resume_attempts = 0
      cancel_resume()
    end
  elseif not resuming then
    -- Playback restarted by something other than a retry (the user pressing
    -- play, or a new station loading), so any pending recovery is moot.
    clear_user_pause_marker()
    forget_device_loss()
  end
  schedule_update()
end)

local function device_names(list)
  local names = {}
  if type(list) == "table" then
    for _, device in ipairs(list) do
      if type(device) == "table" and type(device.name) == "string" then
        names[device.name] = true
      end
    end
  end
  return names
end

local function has_new_device(current, previous)
  for name in pairs(current) do
    if not previous[name] then return true end
  end
  return false
end

-- A device appearing is the cue to try again. Compared as a set rather than a
-- count, so a swap that leaves the total unchanged still registers. The trigger
-- does not have to be right: a premature attempt simply bounces and backs off.
mp.observe_property("audio-device-list", "native", function(_, list)
  local current = device_names(list)
  local previous = known_devices
  known_devices = current
  if previous == nil then return end
  if not device_lost then return end
  if not has_new_device(current, previous) then return end

  -- Fresh budget: something genuinely changed for the better.
  resume_attempts = 0
  schedule_resume(resume_debounce_seconds)
end)

for _, property in ipairs({
  "mute", "media-title", "playlist-pos", "playlist-count", "volume"
}) do
  mp.observe_property(property, "native", schedule_update)
end

mp.register_event("start-file", function()
  station_loaded = false
  schedule_update()
end)
mp.register_event("file-loaded", function()
  station_loaded = true
  schedule_update()
end)
mp.register_event("end-file", function()
  station_loaded = false
  schedule_update()
end)
mp.register_event("idle", function()
  station_loaded = false
  schedule_update()
end)
mp.register_script_message("radio-atlas-reload", function()
  queue = nil
  schedule_update()
end)
mp.register_event("shutdown", function()
  if update_timer then update_timer:kill() end
  write_status({
    running = false,
    paused = false,
    muted = false,
    title = "",
    playlistPosition = -1,
    playlistCount = 0,
    volume = last_volume,
    loaded = false,
    station = empty_station()
  })
end)

schedule_update()
