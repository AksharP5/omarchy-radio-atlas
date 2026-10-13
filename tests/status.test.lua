local audio_device = assert(os.getenv("RADIO_ATLAS_TEST_AUDIO_DEVICE"))
local expected_output = assert(os.getenv("RADIO_ATLAS_TEST_EXPECTED_OUTPUT"))
local artwork = ""
local expected_artwork = ""

package.preload["mp"] = function()
  return {
    get_property = function(name, default)
      if name == "audio-device" then return audio_device end
      return default
    end,
    get_property_number = function(_, default) return default end,
    get_property_native = function(name, default)
      if name == "user-data/radio-atlas-artwork" then return artwork end
      return default
    end,
    get_property_bool = function(_, default) return default end,
    set_property_bool = function() end,
    add_timeout = function(_, callback)
      callback()
      return { kill = function() end }
    end,
    observe_property = function() end,
    add_hook = function() end,
    register_event = function() end,
    register_script_message = function() end
  }
end

package.preload["mp.utils"] = function()
  return {
    parse_json = function() return nil end,
    format_json = function(state)
      assert(state.output == expected_output,
        string.format("expected output %q, got %q", expected_output, state.output))
      assert(state.artwork == expected_artwork, "Status must publish only local artwork strings")
      return "{}"
    end
  }
end

for _, case in ipairs({
  { value = "file:///tmp/cache%20%23%3F/image.svg", expected = "file:///tmp/cache%20%23%3F/image.svg" },
  { value = "http://127.0.0.1/private.svg", expected = "" },
  { value = "https://icons.example/image.svg", expected = "" },
  { value = "file://remote/image.svg", expected = "" },
  { value = 42, expected = "" },
  { value = false, expected = "" },
  { value = {}, expected = "" },
  { expected = "" },
}) do
  artwork = case.value
  expected_artwork = case.expected
  dofile(assert(arg[1]))
end
