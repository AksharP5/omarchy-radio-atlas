local mp = require("mp")
local utils = require("mp.utils")

local status_path = os.getenv("RADIO_ATLAS_STATUS_FILE")
local queue_path = os.getenv("RADIO_ATLAS_QUEUE_FILE")
local queue = nil
local update_timer = nil
local last_volume = 70
local station_loaded = false

local function empty_station()
  return { uuid = "", name = "", country = "", countryCode = "" }
end

local function read_queue()
  if queue then return queue end
  queue = {}
  if not queue_path then return queue end

  local file = io.open(queue_path, "r")
  if not file then return queue end
  local parsed = utils.parse_json(file:read("*a"))
  file:close()
  if type(parsed) == "table" then queue = parsed end
  return queue
end

local function write_status(state)
  if not status_path then return end
  local temporary = status_path .. ".tmp"
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
    title = mp.get_property("media-title", ""),
    playlistPosition = position,
    playlistCount = mp.get_property_number("playlist-count", 0),
    volume = last_volume,
    loaded = station_loaded,
    station = read_queue()[position + 1] or empty_station()
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

for _, property in ipairs({
  "pause", "mute", "media-title", "playlist-pos", "playlist-count", "volume"
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
