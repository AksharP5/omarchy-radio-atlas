local audio_device = assert(os.getenv("RADIO_ATLAS_TEST_AUDIO_DEVICE"))
local expected_output = assert(os.getenv("RADIO_ATLAS_TEST_EXPECTED_OUTPUT"))

package.preload["mp"] = function()
  return {
    get_property = function(name, default)
      if name == "audio-device" then return audio_device end
      return default
    end,
    get_property_number = function(_, default) return default end,
    get_property_bool = function(_, default) return default end,
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
      return "{}"
    end
  }
end

dofile(assert(arg[1]))
