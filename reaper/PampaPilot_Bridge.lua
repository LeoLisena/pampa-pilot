-- PampaPilot: puente local y verificable para REAPER.
-- El script sólo ejecuta las acciones registradas en ACTIONS.

local BRIDGE_VERSION = "0.11.1"
local PROTOCOL_VERSION = "0.1"
local MAX_MESSAGE_BYTES = 1000000
local POLL_INTERVAL_SECONDS = 0.05
local SECTION = "PampaPilotBridge"
local INSTANCE_KEY = "active_instance"

local _, _, action_section_id, action_command_id = reaper.get_action_context()

local function set_action_toggle_state(enabled)
  if type(action_section_id) ~= "number" or type(action_command_id) ~= "number"
    or action_command_id <= 0 then
    return
  end
  reaper.SetToggleCommandState(action_section_id, action_command_id, enabled and 1 or 0)
  reaper.RefreshToolbar2(action_section_id, action_command_id)
end

local separator = package.config:sub(1, 1)
local source = debug.getinfo(1, "S").source
local script_path = source:sub(1, 1) == "@" and source:sub(2) or source
local script_dir = script_path:match("^(.*[\\/])") or ("." .. separator)
local json = dofile(script_dir .. "vendor" .. separator .. "json.lua")

local function load_bridge_config()
  local config_path = script_dir .. "bridge_config.local.json"
  local stream = io.open(config_path, "rb")
  if not stream then
    return {
      ipc_root = reaper.GetResourcePath() .. separator .. "PampaPilot" .. separator .. "ipc",
      allowed_media_roots = {},
      allowed_project_roots = {},
    }
  end
  local content = stream:read("*a")
  stream:close()
  local config = json.decode(content)
  if type(config) ~= "table" then error("bridge_config.local.json debe ser un objeto") end
  if type(config.ipc_root) ~= "string" or config.ipc_root == "" then
    error("bridge_config.local.json no contiene ipc_root válido")
  end
  if config.allowed_media_roots ~= nil and type(config.allowed_media_roots) ~= "table" then
    error("allowed_media_roots debe ser un arreglo")
  end
  if config.allowed_project_roots ~= nil and type(config.allowed_project_roots) ~= "table" then
    error("allowed_project_roots debe ser un arreglo")
  end
  return {
    ipc_root = config.ipc_root,
    allowed_media_roots = config.allowed_media_roots or {},
    allowed_project_roots = config.allowed_project_roots or {},
  }
end

local bridge_config = load_bridge_config()
local ipc_root = bridge_config.ipc_root
local allowed_media_roots = bridge_config.allowed_media_roots
local allowed_project_roots = bridge_config.allowed_project_roots
local pending_dir = ipc_root .. separator .. "requests" .. separator .. "pending"
local processing_dir = ipc_root .. separator .. "requests" .. separator .. "processing"
local responses_dir = ipc_root .. separator .. "responses"
local quarantine_dir = ipc_root .. separator .. "quarantine"

local instance_token = reaper.genGuid()
local last_poll_at = 0.0
local transaction_stack = {}

local function join(directory, filename) return directory .. separator .. filename end

local function ensure_directories()
  reaper.RecursiveCreateDirectory(pending_dir, 0)
  reaper.RecursiveCreateDirectory(processing_dir, 0)
  reaper.RecursiveCreateDirectory(responses_dir, 0)
  reaper.RecursiveCreateDirectory(quarantine_dir, 0)
end

local function file_exists(path)
  local stream = io.open(path, "rb")
  if stream then stream:close(); return true end
  return false
end

local function read_file(path)
  local stream, open_error = io.open(path, "rb")
  if not stream then error("no se pudo abrir el mensaje: " .. tostring(open_error)) end
  local size = stream:seek("end")
  if not size or size > MAX_MESSAGE_BYTES then
    stream:close()
    error("mensaje demasiado grande")
  end
  stream:seek("set", 0)
  local content = stream:read("*a")
  stream:close()
  return content
end

local function atomic_write(path, content)
  if #content > MAX_MESSAGE_BYTES then error("respuesta demasiado grande") end
  local temporary = path .. ".tmp"
  local stream, open_error = io.open(temporary, "wb")
  if not stream then error("no se pudo crear la respuesta: " .. tostring(open_error)) end
  local ok, write_error = stream:write(content)
  stream:flush()
  stream:close()
  if not ok then os.remove(temporary); error("falló la escritura: " .. tostring(write_error)) end
  os.remove(path)
  local renamed, rename_error = os.rename(temporary, path)
  if not renamed then os.remove(temporary); error("falló la publicación: " .. tostring(rename_error)) end
end

local function current_project()
  local project, project_path = reaper.EnumProjects(-1, "")
  if not project then error("no hay un proyecto activo") end
  return project, project_path or ""
end

local function project_ref(project, project_path)
  return tostring(project) .. ":" .. project_path
end

local function project_context()
  local project, project_path = current_project()
  return project, project_path, project_ref(project, project_path)
end

local function require_string(value, name, maximum)
  if type(value) ~= "string" or value == "" then error(name .. " debe ser texto no vacío") end
  if maximum and #value > maximum then error(name .. " supera el tamaño permitido") end
  if value:find("[%z\1-\31]") then error(name .. " contiene caracteres de control") end
  return value
end

local function require_number(value, name, minimum, maximum)
  if type(value) ~= "number" or value ~= value then error(name .. " debe ser numérico") end
  if minimum and value < minimum then error(name .. " está fuera de rango") end
  if maximum and value > maximum then error(name .. " está fuera de rango") end
  return value
end

local function require_boolean(value, name)
  if type(value) ~= "boolean" then error(name .. " debe ser booleano") end
  return value
end

local function db_to_amplitude(db)
  return 10 ^ (db / 20)
end

local function amplitude_to_db(amplitude)
  if amplitude <= 0 then return -150.0 end
  return 20 * math.log(amplitude, 10)
end

local function normalized_absolute_path(value, name)
  local path = require_string(value, name, 4096)
  local absolute = separator == "\\" and path:match("^%a:[\\/]") or path:sub(1, 1) == "/"
  if not absolute then error(name .. " debe ser una ruta absoluta") end
  for segment in path:gmatch("[^\\/]+") do
    if segment == ".." then error(name .. " no puede contener segmentos ..") end
  end
  local normalized = path:gsub("[\\/]", separator)
  while #normalized > 3 and normalized:sub(-1) == separator do
    normalized = normalized:sub(1, -2)
  end
  if separator == "\\" then normalized = normalized:lower() end
  return normalized
end

local function require_allowed_audio_path(value)
  local path = require_string(value, "file_path", 4096)
  if path:lower():sub(-4) ~= ".wav" then error("el MVP sólo permite archivos WAV") end
  local candidate = normalized_absolute_path(path, "file_path")
  local allowed = false
  for _, root_value in ipairs(allowed_media_roots) do
    local root = normalized_absolute_path(root_value, "allowed_media_roots")
    local prefix = root .. separator
    if candidate:sub(1, #prefix) == prefix then
      allowed = true
      break
    end
  end
  if not allowed then error("file_path está fuera de allowed_media_roots") end
  local stream = io.open(path, "rb")
  if not stream then error("no se puede leer el archivo WAV") end
  stream:close()
  return path
end

local function require_allowed_midi_path(value)
  local path = require_string(value, "file_path", 4096)
  local lower = path:lower()
  if lower:sub(-4) ~= ".mid" and lower:sub(-5) ~= ".midi" then
    error("file_path debe terminar en .mid o .midi")
  end
  local candidate = normalized_absolute_path(path, "file_path")
  local allowed = false
  for _, root_value in ipairs(allowed_media_roots) do
    local root = normalized_absolute_path(root_value, "allowed_media_roots")
    local prefix = root .. separator
    if candidate:sub(1, #prefix) == prefix then
      allowed = true
      break
    end
  end
  if not allowed then error("file_path está fuera de allowed_media_roots") end
  local stream = io.open(path, "rb")
  if not stream then error("no se puede leer el archivo MIDI") end
  stream:close()
  return path
end

local function require_allowed_project_path(value)
  local path = require_string(value, "project_path", 4096)
  if path:lower():sub(-4) ~= ".rpp" then error("project_path debe terminar en .rpp") end
  local candidate = normalized_absolute_path(path, "project_path")
  local allowed = false
  for _, root_value in ipairs(allowed_project_roots) do
    local root = normalized_absolute_path(root_value, "allowed_project_roots")
    local prefix = root .. separator
    if candidate:sub(1, #prefix) == prefix then
      allowed = true
      break
    end
  end
  if not allowed then error("project_path está fuera de allowed_project_roots") end
  return path
end

local function require_project(params)
  if type(params) ~= "table" then error("params debe ser un objeto") end
  local project, path, ref = project_context()
  if params.project_ref ~= ref then
    error("el proyecto activo cambió; vuelva a consultar health_check")
  end
  return project, path, ref
end

local function find_track_by_guid(project, guid)
  require_string(guid, "track_guid", 64)
  for index = 0, reaper.CountTracks(project) - 1 do
    local track = reaper.GetTrack(project, index)
    if track and reaper.GetTrackGUID(track) == guid then return track, index end
  end
  error("no existe una pista con el GUID indicado")
end

local function read_track(track, index)
  local _, name = reaper.GetSetMediaTrackInfo_String(track, "P_NAME", "", false)
  local volume = reaper.GetMediaTrackInfo_Value(track, "D_VOL")
  return {
    guid = reaper.GetTrackGUID(track),
    index = index,
    name = name or "",
    volume = volume,
    volume_db = amplitude_to_db(volume),
    pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN"),
    width = reaper.GetMediaTrackInfo_Value(track, "D_WIDTH"),
    pan_mode = reaper.GetMediaTrackInfo_Value(track, "I_PANMODE"),
    pan_law = reaper.GetMediaTrackInfo_Value(track, "D_PANLAW"),
    pan_law_flags = reaper.GetMediaTrackInfo_Value(track, "I_PANLAW_FLAGS"),
    automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE"),
    muted = reaper.GetMediaTrackInfo_Value(track, "B_MUTE") ~= 0,
    solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO"),
    fx_count = reaper.TrackFX_GetCount(track),
  }
end

local function read_fx(track, fx_index, include_parameters)
  local name_ok, name = reaper.TrackFX_GetFXName(track, fx_index)
  local guid = reaper.TrackFX_GetFXGUID(track, fx_index)
  if not name_ok or not name or name == "" then error("REAPER no devolvió el nombre del FX") end
  if not guid or guid == "" then error("REAPER no devolvió el GUID del FX") end
  local state = {
    index = fx_index,
    guid = guid,
    name = name,
    enabled = reaper.TrackFX_GetEnabled(track, fx_index),
    offline = reaper.TrackFX_GetOffline(track, fx_index),
    parameter_count = reaper.TrackFX_GetNumParams(track, fx_index),
  }
  if include_parameters then
    state.parameters = {}
    for parameter_index = 0, state.parameter_count - 1 do
      local _, parameter_name = reaper.TrackFX_GetParamName(track, fx_index, parameter_index)
      local _, parameter_ident = reaper.TrackFX_GetParamIdent(track, fx_index, parameter_index)
      local _, formatted = reaper.TrackFX_GetFormattedParamValue(
        track, fx_index, parameter_index)
      state.parameters[#state.parameters + 1] = {
        index = parameter_index,
        name = parameter_name or "",
        ident = parameter_ident or "",
        normalized = reaper.TrackFX_GetParamNormalized(track, fx_index, parameter_index),
        formatted = formatted or "",
      }
    end
  end
  return state
end

local function read_fx_chain(track, include_parameters)
  local chain = {}
  for fx_index = 0, reaper.TrackFX_GetCount(track) - 1 do
    chain[#chain + 1] = read_fx(track, fx_index, include_parameters)
  end
  return chain
end

local function find_fx_by_guid(track, guid)
  require_string(guid, "fx_guid", 64)
  for fx_index = 0, reaper.TrackFX_GetCount(track) - 1 do
    if reaper.TrackFX_GetFXGUID(track, fx_index) == guid then return fx_index end
  end
  error("no existe un FX con el GUID indicado en la pista")
end

local function find_fx_parameter_by_ident(track, fx_index, ident)
  for parameter_index = 0, reaper.TrackFX_GetNumParams(track, fx_index) - 1 do
    local ok, observed_ident = reaper.TrackFX_GetParamIdent(
      track, fx_index, parameter_index)
    if ok and observed_ident == ident then return parameter_index end
  end
  error("el FX no expone el parámetro esperado: " .. ident)
end

local function parse_formatted_number(value, expected_unit)
  if type(value) ~= "string" then return nil end
  local normalized = value:gsub(",", ".")
  -- Lua patterns no implementa el cuantificador '?' de las expresiones
  -- regulares. Se prueban explícitamente signo y parte decimal opcionales.
  local token = normalized:match("[+-]%d+%.%d+")
    or normalized:match("[+-]%d+")
    or normalized:match("%d+%.%d+")
    or normalized:match("%d+")
  local number = token and tonumber(token) or nil
  if number == nil then return nil end

  -- Algunos plugins cambian automáticamente la unidad mostrada según la
  -- magnitud (por ejemplo, ReaLimit muestra milisegundos y luego segundos).
  -- La calibración debe comparar siempre en la unidad solicitada.
  if expected_unit == "ms" then
    local compact = normalized:gsub("%s+", "")
    if compact:match("[mM][sS]$") then
      return number
    end
    if compact:match("[uU][sS]$") then
      return number / 1000.0
    end
    if compact:match("[sS]$") then
      return number * 1000.0
    end
  end
  return number
end

local function observed_parameter_number(
    track, fx_index, parameter_index, normalized, expected_unit)
  -- Algunos FX no informan de forma consistente el rango mediante
  -- TrackFX_FormatParamValueNormalized. Calibramos dentro de la transacción:
  -- escribimos un valor normalizado y leemos lo que el propio FX muestra.
  if not reaper.TrackFX_SetParamNormalized(
      track, fx_index, parameter_index, normalized) then
    error("REAPER rechazó un valor de calibración del FX")
  end
  local ok, formatted = reaper.TrackFX_GetFormattedParamValue(
    track, fx_index, parameter_index)
  if not ok then error("REAPER no pudo leer un parámetro del FX") end
  return parse_formatted_number(formatted, expected_unit), formatted or ""
end

local function normalized_for_formatted_target(
    track, fx_index, parameter_index, target, tolerance, expected_unit)
  local best_normalized, best_value, best_formatted = nil, nil, ""
  local low, high, low_value, high_value = nil, nil, nil, nil
  local previous_normalized, previous_value = nil, nil
  local observed_minimum, observed_maximum = nil, nil

  -- La representación VST no siempre es monótona en los extremos. Recorremos
  -- primero la curva y sólo después hacemos búsqueda binaria en un intervalo
  -- que realmente contenga el valor solicitado.
  for step = 0, 256 do
    local normalized = step / 256
    local value, formatted = observed_parameter_number(
      track, fx_index, parameter_index, normalized, expected_unit)
    if value ~= nil then
      observed_minimum = observed_minimum and math.min(observed_minimum, value) or value
      observed_maximum = observed_maximum and math.max(observed_maximum, value) or value
      if best_value == nil or math.abs(value - target) < math.abs(best_value - target) then
        best_normalized, best_value, best_formatted = normalized, value, formatted
      end
      if previous_value ~= nil
          and (target - previous_value) * (target - value) <= 0 then
        low, high = previous_normalized, normalized
        low_value, high_value = previous_value, value
        break
      end
      previous_normalized, previous_value = normalized, value
    end
  end
  if best_value == nil then
    error("el parámetro del FX no tiene un rango numérico observable")
  end
  if math.abs(best_value - target) <= tolerance then
    return best_normalized
  end
  if low == nil or high == nil then
    error(
      "el valor solicitado está fuera del rango observable del FX"
      .. " (mínimo=" .. tostring(observed_minimum)
      .. ", máximo=" .. tostring(observed_maximum)
      .. ", más cercano=" .. tostring(best_formatted) .. ")")
  end
  local ascending = high_value >= low_value

  for _ = 1, 48 do
    local middle = (low + high) / 2
    local middle_value = observed_parameter_number(
      track, fx_index, parameter_index, middle, expected_unit)
    if middle_value == nil then
      -- Sólo debería ocurrir pegado a un extremo infinito.
      if middle < 0.5 then low = middle else high = middle end
    else
      if math.abs(middle_value - target) < math.abs(best_value - target) then
        best_normalized, best_value = middle, middle_value
      end
      if ascending then
        if middle_value < target then low = middle else high = middle end
      else
        if middle_value > target then low = middle else high = middle end
      end
    end
  end
  if math.abs(best_value - target) > tolerance then
    error("el FX no puede representar el valor solicitado con precisión suficiente")
  end
  return best_normalized
end

local function set_numeric_parameter(
    track, fx_index, ident, target, tolerance, expected_unit)
  local parameter_index = find_fx_parameter_by_ident(track, fx_index, ident)
  local found, normalized_or_error = pcall(
    normalized_for_formatted_target,
    track, fx_index, parameter_index, target, tolerance, expected_unit)
  if not found then error(ident .. ": " .. tostring(normalized_or_error)) end
  local normalized = normalized_or_error
  if not reaper.TrackFX_SetParamNormalized(
      track, fx_index, parameter_index, normalized) then
    error("REAPER rechazó el parámetro " .. ident)
  end
  local _, formatted = reaper.TrackFX_GetFormattedParamValue(
    track, fx_index, parameter_index)
  local observed = parse_formatted_number(formatted, expected_unit)
  if observed == nil or math.abs(observed - target) > tolerance then
    error("la lectura posterior no coincide para " .. ident)
  end
end

local function set_reacomp_boolean_parameter(track, fx_index, ident, target)
  local parameter_index = find_fx_parameter_by_ident(track, fx_index, ident)
  local normalized = target and 1.0 or 0.0
  if not reaper.TrackFX_SetParamNormalized(
      track, fx_index, parameter_index, normalized) then
    error("REAPER rechazó el parámetro " .. ident)
  end
  local observed = reaper.TrackFX_GetParamNormalized(track, fx_index, parameter_index)
  if math.abs(observed - normalized) > 0.000001 then
    error("la lectura posterior no coincide para " .. ident)
  end
end

local REAEQ_BAND_TYPES = {
  high_pass = 0,
  low_shelf = 1,
  bell = 2,
  notch = 3,
  high_shelf = 4,
  low_pass = 5,
  band_pass = 6,
  parallel_band_pass = 7,
}

local REAEQ_BAND_TYPE_NAMES = {}
for name, value in pairs(REAEQ_BAND_TYPES) do REAEQ_BAND_TYPE_NAMES[value] = name end

local REAEQ_PARAM_TYPE_NAMES = { [0] = "frequency", [1] = "gain", [2] = "q" }

local function require_integer(value, name, minimum, maximum)
  local number = require_number(value, name, minimum, maximum)
  if number % 1 ~= 0 then error(name .. " debe ser entero") end
  return number
end

local function require_reaeq(track, fx_index)
  local fx = read_fx(track, fx_index, false)
  if not fx.name:lower():find("reaeq", 1, true) then
    error("el FX indicado no es ReaEQ")
  end
  if not fx.enabled or fx.offline then error("ReaEQ debe estar activo y online") end
  return fx
end

local function require_reacomp(track, fx_index)
  local fx = read_fx(track, fx_index, false)
  if not fx.name:lower():find("reacomp", 1, true) then
    error("el FX indicado no es ReaComp")
  end
  if not fx.enabled or fx.offline then error("ReaComp debe estar activo y online") end
  return fx
end

local function require_realimit(track, fx_index)
  local fx = read_fx(track, fx_index, false)
  if not fx.name:lower():find("realimit", 1, true) then
    error("el FX indicado no es ReaLimit")
  end
  if not fx.enabled or fx.offline then error("ReaLimit debe estar activo y online") end
  return fx
end

local function read_reaeq_band(track, fx_index, band_type, band_index)
  local parameters = {}
  for parameter_index = 0, reaper.TrackFX_GetNumParams(track, fx_index) - 1 do
    local ok, observed_type, observed_index, parameter_type, normalized =
      reaper.TrackFX_GetEQParam(track, fx_index, parameter_index)
    if ok and observed_type == band_type and observed_index == band_index then
      local formatted_ok, formatted = reaper.TrackFX_GetFormattedParamValue(
        track, fx_index, parameter_index)
      if not formatted_ok then error("REAPER no formateó un parámetro de ReaEQ") end
      parameters[REAEQ_PARAM_TYPE_NAMES[parameter_type] or tostring(parameter_type)] = {
        index = parameter_index,
        normalized = normalized,
        formatted = formatted or "",
      }
    end
  end
  if not parameters.frequency or not parameters.gain or not parameters.q then
    error("ReaEQ no contiene la banda solicitada")
  end
  return {
    band_type = REAEQ_BAND_TYPE_NAMES[band_type],
    band_type_code = band_type,
    band_index = band_index,
    enabled = reaper.TrackFX_GetEQBandEnabled(
      track, fx_index, band_type, band_index),
    parameters = parameters,
  }
end

local function validate_reaeq_parameters(params)
  if type(params) ~= "table" then error("parameters de ReaEQ debe ser un objeto") end
  local band_type_name = require_string(params.band_type, "band_type", 32)
  local band_type = REAEQ_BAND_TYPES[band_type_name]
  if band_type == nil then error("tipo de banda ReaEQ no permitido") end
  return {
    band_type_name = band_type_name,
    band_type = band_type,
    band_index = require_integer(params.band_index, "band_index", 0, 7),
    frequency_hz = require_number(params.frequency_hz, "frequency_hz", 20.0, 20000.0),
    gain_db = require_number(params.gain_db, "gain_db", -24.0, 24.0),
    q = require_number(params.q, "q", 0.1, 10.0),
    enabled = require_boolean(params.enabled, "enabled"),
  }
end

local function apply_reaeq_parameters(track, fx_index, spec)
  require_reaeq(track, fx_index)
  read_reaeq_band(track, fx_index, spec.band_type, spec.band_index)
  if not reaper.TrackFX_SetEQParam(
      track, fx_index, spec.band_type, spec.band_index, 0, spec.frequency_hz, false) then
    error("REAPER rechazó la frecuencia de ReaEQ")
  end
  if not reaper.TrackFX_SetEQParam(
      track, fx_index, spec.band_type, spec.band_index, 1,
      db_to_amplitude(spec.gain_db), false) then
    error("REAPER rechazó la ganancia de ReaEQ")
  end
  if not reaper.TrackFX_SetEQParam(
      track, fx_index, spec.band_type, spec.band_index, 2, spec.q, false) then
    error("REAPER rechazó Q de ReaEQ")
  end
  if not reaper.TrackFX_SetEQBandEnabled(
      track, fx_index, spec.band_type, spec.band_index, spec.enabled) then
    error("REAPER rechazó habilitar o deshabilitar la banda ReaEQ")
  end
  local band = read_reaeq_band(track, fx_index, spec.band_type, spec.band_index)
  if band.band_type ~= spec.band_type_name then error("el tipo de banda leído no coincide") end
  if band.enabled ~= spec.enabled then error("el estado leído de la banda no coincide") end
  local frequency_observed = parse_formatted_number(band.parameters.frequency.formatted)
  local gain_observed = parse_formatted_number(band.parameters.gain.formatted)
  local q_observed = parse_formatted_number(band.parameters.q.formatted)
  if not frequency_observed
    or math.abs(frequency_observed - spec.frequency_hz)
      > math.max(0.11, spec.frequency_hz * 0.001) then
    error("la frecuencia leída de ReaEQ no coincide")
  end
  if not gain_observed or math.abs(gain_observed - spec.gain_db) > 0.11 then
    error("la ganancia leída de ReaEQ no coincide")
  end
  if not q_observed or math.abs(q_observed - spec.q) > 0.011 then
    error("Q leído de ReaEQ no coincide")
  end
  return band
end

local function validate_reacomp_parameters(params)
  if type(params) ~= "table" then error("parameters de ReaComp debe ser un objeto") end
  return {
    threshold_db = require_number(params.threshold_db, "threshold_db", -60.0, 0.0),
    ratio = require_number(params.ratio, "ratio", 1.0, 10.0),
    attack_ms = require_number(params.attack_ms, "attack_ms", 0.0, 200.0),
    release_ms = require_number(params.release_ms, "release_ms", 5.0, 1000.0),
    knee_db = require_number(params.knee_db, "knee_db", 0.0, 12.0),
    rms_ms = require_number(params.rms_ms, "rms_ms", 0.0, 100.0),
    auto_makeup = require_boolean(params.auto_makeup, "auto_makeup"),
    auto_release = require_boolean(params.auto_release, "auto_release"),
  }
end

local function apply_reacomp_parameters(track, fx_index, spec, expected_guid)
  require_reacomp(track, fx_index)
  set_numeric_parameter(track, fx_index, "0:_Threshold", spec.threshold_db, 0.11)
  set_numeric_parameter(track, fx_index, "1:_Ratio", spec.ratio, 0.011)
  set_numeric_parameter(track, fx_index, "2:_Attack", spec.attack_ms, 0.11, "ms")
  set_numeric_parameter(track, fx_index, "3:_Release", spec.release_ms, 1.01, "ms")
  set_numeric_parameter(track, fx_index, "13:_RMS_size", spec.rms_ms, 0.11, "ms")
  set_numeric_parameter(track, fx_index, "14:_Knee", spec.knee_db, 0.11)
  set_reacomp_boolean_parameter(
    track, fx_index, "15:_Auto_Make_Up_Gain", spec.auto_makeup)
  set_reacomp_boolean_parameter(track, fx_index, "16:_Auto_Release", spec.auto_release)
  local fx = read_fx(track, fx_index, true)
  if expected_guid and fx.guid ~= expected_guid then error("el GUID de ReaComp cambió") end
  return fx
end

local function validate_realimit_parameters(params)
  if type(params) ~= "table" then error("parameters de ReaLimit debe ser un objeto") end
  local spec = {
    threshold_db = require_number(params.threshold_db, "threshold_db", -30.0, 0.0),
    ceiling_db = require_number(params.ceiling_db, "ceiling_db", -12.0, 0.0),
    release_ms = require_number(params.release_ms, "release_ms", 0.0, 1000.0),
  }
  if spec.threshold_db > spec.ceiling_db then
    error("threshold_db no puede superar ceiling_db")
  end
  return spec
end

local function apply_realimit_parameters(master, fx_index, spec, expected_guid)
  require_realimit(master, fx_index)
  set_numeric_parameter(master, fx_index, "0:_Threshold", spec.threshold_db, 0.11)
  set_numeric_parameter(master, fx_index, "1:_Ceiling", spec.ceiling_db, 0.11)
  set_numeric_parameter(master, fx_index, "2:_Release", spec.release_ms, 0.11, "ms")
  local fx = read_fx(master, fx_index, true)
  if expected_guid and fx.guid ~= expected_guid then error("el GUID de ReaLimit cambió") end
  return fx
end

local function count_fx_by_name_fragment(track, fragment)
  local count = 0
  for fx_index = 0, reaper.TrackFX_GetCount(track) - 1 do
    local fx = read_fx(track, fx_index, false)
    if fx.name:lower():find(fragment, 1, true) then count = count + 1 end
  end
  return count
end

local function read_imported_item(item, take)
  local item_ok, item_guid = reaper.GetSetMediaItemInfo_String(item, "GUID", "", false)
  local take_ok, take_guid = reaper.GetSetMediaItemTakeInfo_String(take, "GUID", "", false)
  if not item_ok or item_guid == "" then error("REAPER no devolvió GUID del ítem") end
  if not take_ok or take_guid == "" then error("REAPER no devolvió GUID de la toma") end
  local source = reaper.GetMediaItemTake_Source(take)
  if not source then error("la toma no tiene fuente de audio") end
  local source_length, length_is_qn = reaper.GetMediaSourceLength(source)
  return {
    guid = item_guid,
    position_seconds = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
    length_seconds = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
    timebase = reaper.GetMediaItemInfo_Value(item, "C_BEATATTACHMODE"),
    auto_stretch = reaper.GetMediaItemInfo_Value(item, "C_AUTOSTRETCH") ~= 0,
    take = {
      guid = take_guid,
      source_path = reaper.GetMediaSourceFileName(source),
      source_type = reaper.GetMediaSourceType(source),
      source_length = source_length,
      source_length_is_quarter_notes = length_is_qn == true,
      sample_rate = reaper.GetMediaSourceSampleRate(source),
      channels = reaper.GetMediaSourceNumChannels(source),
    },
  }
end

local function snapshot_item_timing(project)
  local snapshot = {}
  for index = 0, reaper.CountMediaItems(project) - 1 do
    local item = reaper.GetMediaItem(project, index)
    local ok, guid = reaper.GetSetMediaItemInfo_String(item, "GUID", "", false)
    if not ok or guid == "" then error("REAPER no devolvió GUID de un ítem") end
    local take = reaper.GetActiveTake(item)
    local take_source = take and reaper.GetMediaItemTake_Source(take) or nil
    local source_type = take_source and reaper.GetMediaSourceType(take_source) or ""
    snapshot[guid] = {
      position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
      length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
      playrate = take and reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE") or nil,
      is_audio = source_type ~= "" and source_type ~= "MIDI",
    }
  end
  return snapshot
end

local function lock_audio_items_to_time(project, snapshot)
  local locked = 0
  for index = 0, reaper.CountMediaItems(project) - 1 do
    local item = reaper.GetMediaItem(project, index)
    local ok, guid = reaper.GetSetMediaItemInfo_String(item, "GUID", "", false)
    if not ok or guid == "" then error("REAPER no devolvió GUID de un ítem") end
    local expected = snapshot[guid]
    if expected and expected.is_audio then
      if not reaper.SetMediaItemInfo_Value(item, "C_BEATATTACHMODE", 0) then
        error("REAPER rechazó el timebase absoluto de un ítem de audio")
      end
      if not reaper.SetMediaItemInfo_Value(item, "C_AUTOSTRETCH", 0) then
        error("REAPER rechazó desactivar auto-stretch en un ítem de audio")
      end
      locked = locked + 1
    end
  end
  return locked
end

local function verify_item_timing_unchanged(project, before)
  local remaining = 0
  for _ in pairs(before) do remaining = remaining + 1 end
  for index = 0, reaper.CountMediaItems(project) - 1 do
    local item = reaper.GetMediaItem(project, index)
    local ok, guid = reaper.GetSetMediaItemInfo_String(item, "GUID", "", false)
    if not ok or guid == "" then error("REAPER no devolvió GUID de un ítem") end
    local expected = before[guid]
    if not expected then error("el cambio de tempo creó o reemplazó un ítem") end
    local position = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
    local take = reaper.GetActiveTake(item)
    local playrate = take and reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE") or nil
    if math.abs(position - expected.position) > 0.000001 then
      error("el cambio de tempo desplazó un ítem")
    end
    if math.abs(length - expected.length) > 0.000001 then
      error("el cambio de tempo alteró la duración de un ítem")
    end
    if playrate ~= expected.playrate
      and (playrate == nil or expected.playrate == nil
        or math.abs(playrate - expected.playrate) > 0.000001) then
      error("el cambio de tempo alteró la velocidad de reproducción de una toma")
    end
    if expected.is_audio then
      if reaper.GetMediaItemInfo_Value(item, "C_BEATATTACHMODE") ~= 0 then
        error("un ítem de audio no quedó fijado a tiempo absoluto")
      end
      if reaper.GetMediaItemInfo_Value(item, "C_AUTOSTRETCH") ~= 0 then
        error("un ítem de audio conserva auto-stretch")
      end
    end
    remaining = remaining - 1
  end
  if remaining ~= 0 then error("el cambio de tempo eliminó un ítem") end
end

local function observations(state_verified)
  return {
    accepted = true,
    state_verified = state_verified == true,
    signal_verified = false,
    perceptually_evaluated = false,
  }
end

local function run_transaction(project, request_id, description, callback)
  local label = "PampaPilot: " .. description .. " [" .. request_id .. "]"
  local before_count = reaper.GetProjectStateChangeCount(project)
  reaper.Undo_BeginBlock2(project)
  local ok, result = xpcall(callback, debug.traceback)
  reaper.Undo_EndBlock2(project, label, -1)
  if not ok then
    if reaper.GetProjectStateChangeCount(project) ~= before_count
      and reaper.Undo_CanUndo2(project) == label then
      reaper.Undo_DoUndo2(project)
    end
    error(result)
  end
  transaction_stack[#transaction_stack + 1] = { request_id = request_id, label = label }
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  return result
end

local ACTIONS = {}

function ACTIONS.health_check(_, _)
  local project, path, ref = project_context()
  return {
    bridge_version = BRIDGE_VERSION,
    protocol_version = PROTOCOL_VERSION,
    reaper_version = reaper.GetAppVersion(),
    resource_path = reaper.GetResourcePath(),
    project_path = path,
    project_ref = ref,
    track_count = reaper.CountTracks(project),
    tempo_bpm = reaper.Master_GetTempo(),
    project_state_change_count = reaper.GetProjectStateChangeCount(project),
  }, observations(true)
end

function ACTIONS.get_project_state(_, _)
  local project, path, ref = project_context()
  local tracks = {}
  for index = 0, reaper.CountTracks(project) - 1 do
    tracks[#tracks + 1] = read_track(reaper.GetTrack(project, index), index)
  end
  return {
    project_ref = ref,
    project_path = path,
    track_count = #tracks,
    tempo_bpm = reaper.Master_GetTempo(),
    project_state_change_count = reaper.GetProjectStateChangeCount(project),
    tracks = tracks,
  }, observations(true)
end

function ACTIONS.get_render_settings(params, _)
  local project, _, ref = require_project(params)
  local function read_string(description, optional)
    local ok, value = reaper.GetSetProjectInfo_String(project, description, "", false)
    if not ok and optional then return "" end
    if not ok then error("REAPER no devolvió " .. description) end
    return value or ""
  end
  local master = reaper.GetMasterTrack(project)
  if not master then error("REAPER no devolvió la pista master") end
  return {
    project_ref = ref,
    project_state_change_count = reaper.GetProjectStateChangeCount(project),
    project_dirty = reaper.GetSetProjectInfo(project, "DIRTY", 0, false) ~= 0,
    project_sample_rate_hz = reaper.GetSetProjectInfo(project, "PROJECT_SRATE", 0, false),
    project_sample_rate_enabled = reaper.GetSetProjectInfo(
      project, "PROJECT_SRATE_USE", 0, false
    ) ~= 0,
    render_settings_flags = reaper.GetSetProjectInfo(project, "RENDER_SETTINGS", 0, false),
    render_bounds_flag = reaper.GetSetProjectInfo(project, "RENDER_BOUNDSFLAG", 0, false),
    render_channels = reaper.GetSetProjectInfo(project, "RENDER_CHANNELS", 0, false),
    render_sample_rate_hz = reaper.GetSetProjectInfo(project, "RENDER_SRATE", 0, false),
    render_start_seconds = reaper.GetSetProjectInfo(project, "RENDER_STARTPOS", 0, false),
    render_end_seconds = reaper.GetSetProjectInfo(project, "RENDER_ENDPOS", 0, false),
    render_tail_flags = reaper.GetSetProjectInfo(project, "RENDER_TAILFLAG", 0, false),
    render_tail_ms = reaper.GetSetProjectInfo(project, "RENDER_TAILMS", 0, false),
    render_add_to_project_flags = reaper.GetSetProjectInfo(
      project, "RENDER_ADDTOPROJ", 0, false
    ),
    render_dither_flags = reaper.GetSetProjectInfo(project, "RENDER_DITHER", 0, false),
    render_normalize_flags = reaper.GetSetProjectInfo(project, "RENDER_NORMALIZE", 0, false),
    render_directory = read_string("RENDER_FILE"),
    render_pattern = read_string("RENDER_PATTERN"),
    render_targets = read_string("RENDER_TARGETS", true),
    render_format_configuration = read_string("RENDER_FORMAT"),
    render_secondary_format_configuration = read_string("RENDER_FORMAT2", true),
    master_fx = read_fx_chain(master, true),
  }, observations(true)
end

function ACTIONS.get_master_track_state(params, _)
  local project, _, ref = require_project(params)
  local master = reaper.GetMasterTrack(project)
  if not master then error("REAPER no devolvió la pista master") end
  return {
    project_ref = ref,
    track = read_track(master, -1),
    fx = read_fx_chain(master, true),
  }, observations(true)
end

function ACTIONS.get_track_state(params, _)
  local project = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  return {
    track = read_track(track, index),
    fx = read_fx_chain(track, true),
  }, observations(true)
end

function ACTIONS.create_track(params, request_id)
  local project, _, ref = require_project(params)
  local name = require_string(params.name, "name", 128)
  local count = reaper.CountTracks(project)
  local index = params.index == nil and count or require_number(params.index, "index", 0, count)
  if index % 1 ~= 0 then error("index debe ser entero") end
  local result = run_transaction(project, request_id, "crear pista", function()
    reaper.InsertTrackInProject(project, index, 0)
    local track = reaper.GetTrack(project, index)
    if not track then error("REAPER no devolvió la pista creada") end
    local named = reaper.GetSetMediaTrackInfo_String(track, "P_NAME", name, true)
    if not named then error("REAPER rechazó el nombre de la pista") end
    local state = read_track(track, index)
    if state.name ~= name then error("la lectura posterior del nombre no coincide") end
    return { project_ref = ref, track = state, transaction_request_id = request_id }
  end)
  return result, observations(true)
end

function ACTIONS.set_track_pan(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local pan = require_number(params.pan, "pan", -1.0, 1.0)
  local pan_mode = reaper.GetMediaTrackInfo_Value(track, "I_PANMODE")
  if pan_mode ~= -1 and pan_mode ~= 0 and pan_mode ~= 3 then
    error("el MVP sólo admite paneo heredado, clásico o balance")
  end
  local automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE")
  if automation_mode ~= 0 then
    error("la pista tiene automatización activa; el MVP no la sobrescribe")
  end
  local result = run_transaction(project, request_id, "ajustar paneo", function()
    local written = reaper.SetMediaTrackInfo_Value(track, "D_PAN", pan)
    if not written then error("REAPER rechazó el valor de paneo") end
    local state = read_track(track, index)
    if math.abs(state.pan - pan) > 0.000001 then
      error("la lectura posterior del paneo no coincide")
    end
    return { project_ref = ref, track = state, transaction_request_id = request_id }
  end)
  return result, observations(true)
end


function ACTIONS.set_track_volume(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local volume_db = require_number(params.volume_db, "volume_db", -60.0, 12.0)
  local amplitude = db_to_amplitude(volume_db)
  local automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE")
  if automation_mode ~= 0 then
    error("la pista tiene automatización activa; el MVP no la sobrescribe")
  end
  local result = run_transaction(project, request_id, "ajustar volumen", function()
    local written = reaper.SetMediaTrackInfo_Value(track, "D_VOL", amplitude)
    if not written then error("REAPER rechazó el valor de volumen") end
    local state = read_track(track, index)
    if math.abs(state.volume - amplitude) > 0.000001 then
      error("la lectura posterior del volumen no coincide")
    end
    if math.abs(state.volume_db - volume_db) > 0.00001 then
      error("la lectura posterior del volumen en dB no coincide")
    end
    return { project_ref = ref, track = state, transaction_request_id = request_id }
  end)
  return result, observations(true)
end


function ACTIONS.set_track_mute(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local muted = require_boolean(params.muted, "muted")
  local automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE")
  if automation_mode ~= 0 then
    error("la pista tiene automatización activa; el MVP no la sobrescribe")
  end
  local result = run_transaction(project, request_id, "ajustar mute", function()
    local written = reaper.SetMediaTrackInfo_Value(track, "B_MUTE", muted and 1 or 0)
    if not written then error("REAPER rechazó el valor de mute") end
    local state = read_track(track, index)
    if state.muted ~= muted then error("la lectura posterior del mute no coincide") end
    return { project_ref = ref, track = state, transaction_request_id = request_id }
  end)
  return result, observations(true)
end


function ACTIONS.set_track_solo(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local soloed = require_boolean(params.soloed, "soloed")
  local result = run_transaction(project, request_id, "ajustar solo", function()
    local written = reaper.SetMediaTrackInfo_Value(track, "I_SOLO", soloed and 2 or 0)
    if not written then error("REAPER rechazó el valor de solo") end
    local state = read_track(track, index)
    if (state.solo ~= 0) ~= soloed then
      error("la lectura posterior del solo no coincide")
    end
    return { project_ref = ref, track = state, transaction_request_id = request_id }
  end)
  return result, observations(true)
end


function ACTIONS.prepare_mix_listening(params, request_id)
  local project, _, ref = require_project(params)
  local plan_id = require_string(params.plan_id, "plan_id", 24)
  if #plan_id ~= 24 or not plan_id:match("^[0-9a-f]+$") then
    error("plan_id debe contener 24 caracteres hexadecimales minúsculos")
  end

  local clear_guids = params.clear_solo_track_guids
  local mute_guids = params.mute_track_guids
  if type(clear_guids) ~= "table" or type(mute_guids) ~= "table" then
    error("las listas de pistas deben ser arrays")
  end
  if #clear_guids > 64 or #mute_guids > 64 or (#clear_guids + #mute_guids) < 1 then
    error("la preparación debe contener entre 1 y 128 cambios")
  end

  local clear_targets = {}
  local mute_targets = {}
  local affected = {}
  local clear_seen = {}
  local mute_seen = {}
  for _, raw_guid in ipairs(clear_guids) do
    local guid = require_string(raw_guid, "clear_solo_track_guid", 64)
    if clear_seen[guid] then error("GUID duplicado en clear_solo_track_guids: " .. guid) end
    clear_seen[guid] = true
    local track, index = find_track_by_guid(project, guid)
    clear_targets[#clear_targets + 1] = { guid = guid, track = track, index = index }
    affected[guid] = { track = track, index = index }
  end
  for _, raw_guid in ipairs(mute_guids) do
    local guid = require_string(raw_guid, "mute_track_guid", 64)
    if mute_seen[guid] then error("GUID duplicado en mute_track_guids: " .. guid) end
    mute_seen[guid] = true
    local track, index = find_track_by_guid(project, guid)
    local automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE")
    if automation_mode ~= 0 then
      error("la pista " .. guid .. " tiene automatización activa")
    end
    mute_targets[#mute_targets + 1] = { guid = guid, track = track, index = index }
    affected[guid] = { track = track, index = index }
  end

  local result = run_transaction(project, request_id, "preparar escucha de mezcla", function()
    for _, target in ipairs(clear_targets) do
      local written = reaper.SetMediaTrackInfo_Value(target.track, "I_SOLO", 0)
      if not written then error("REAPER rechazó quitar solo de " .. target.guid) end
    end
    for _, target in ipairs(mute_targets) do
      local written = reaper.SetMediaTrackInfo_Value(target.track, "B_MUTE", 1)
      if not written then error("REAPER rechazó mutear " .. target.guid) end
    end

    local tracks = {}
    for guid, target in pairs(affected) do
      local state = read_track(target.track, target.index)
      if clear_seen[guid] and state.solo ~= 0 then
        error("la lectura posterior del solo no coincide en " .. guid)
      end
      if mute_seen[guid] and not state.muted then
        error("la lectura posterior del mute no coincide en " .. guid)
      end
      tracks[#tracks + 1] = state
    end
    table.sort(tracks, function(left, right) return left.index < right.index end)
    return {
      project_ref = ref,
      plan_id = plan_id,
      tracks = tracks,
      cleared_solo_count = #clear_targets,
      muted_count = #mute_targets,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end


function ACTIONS.apply_track_mix_batch(params, request_id)
  local project, _, ref = require_project(params)
  if type(params.items) ~= "table" or #params.items < 1 or #params.items > 64 then
    error("items debe contener entre 1 y 64 ajustes")
  end

  local targets = {}
  local seen = {}
  for position, item in ipairs(params.items) do
    if type(item) ~= "table" then error("cada ajuste debe ser un objeto") end
    local guid = require_string(item.track_guid, "track_guid", 64)
    if seen[guid] then error("track_guid duplicado en items: " .. guid) end
    seen[guid] = true

    local track, index = find_track_by_guid(project, guid)
    local volume_db = item.volume_db == nil
      and nil or require_number(item.volume_db, "volume_db", -60.0, 12.0)
    local pan = item.pan == nil
      and nil or require_number(item.pan, "pan", -1.0, 1.0)
    local muted = item.muted == nil
      and nil or require_boolean(item.muted, "muted")
    if volume_db == nil and pan == nil and muted == nil then
      error("el ajuste " .. position .. " no contiene cambios")
    end

    local automation_mode = reaper.GetMediaTrackInfo_Value(track, "I_AUTOMODE")
    if automation_mode ~= 0 then
      error("la pista " .. guid .. " tiene automatización activa")
    end
    if pan ~= nil then
      local pan_mode = reaper.GetMediaTrackInfo_Value(track, "I_PANMODE")
      if pan_mode ~= -1 and pan_mode ~= 0 and pan_mode ~= 3 then
        error("la pista " .. guid .. " usa un modo de paneo no admitido")
      end
    end
    targets[#targets + 1] = {
      track = track,
      index = index,
      guid = guid,
      volume_db = volume_db,
      pan = pan,
      muted = muted,
    }
  end

  local result = run_transaction(project, request_id, "aplicar mezcla estática", function()
    local states = {}
    for _, target in ipairs(targets) do
      if target.volume_db ~= nil then
        if not reaper.SetMediaTrackInfo_Value(
          target.track, "D_VOL", db_to_amplitude(target.volume_db)) then
          error("REAPER rechazó el volumen de " .. target.guid)
        end
      end
      if target.pan ~= nil then
        if not reaper.SetMediaTrackInfo_Value(target.track, "D_PAN", target.pan) then
          error("REAPER rechazó el paneo de " .. target.guid)
        end
      end
      if target.muted ~= nil then
        if not reaper.SetMediaTrackInfo_Value(
          target.track, "B_MUTE", target.muted and 1 or 0) then
          error("REAPER rechazó el mute de " .. target.guid)
        end
      end

      local state = read_track(target.track, target.index)
      if target.volume_db ~= nil and math.abs(state.volume_db - target.volume_db) > 0.00001 then
        error("la lectura posterior del volumen no coincide en " .. target.guid)
      end
      if target.pan ~= nil and math.abs(state.pan - target.pan) > 0.000001 then
        error("la lectura posterior del paneo no coincide en " .. target.guid)
      end
      if target.muted ~= nil and state.muted ~= target.muted then
        error("la lectura posterior del mute no coincide en " .. target.guid)
      end
      states[#states + 1] = state
    end
    return {
      project_ref = ref,
      tracks = states,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end


function ACTIONS.add_stock_fx(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local fx_type = require_string(params.fx_type, "fx_type", 32)
  local plugin_name
  local expected_name
  local description
  if fx_type == "reacomp" then
    plugin_name, expected_name, description = "ReaComp (Cockos)", "reacomp", "agregar ReaComp"
  elseif fx_type == "reaeq" then
    plugin_name, expected_name, description = "ReaEQ (Cockos)", "reaeq", "agregar ReaEQ"
  else
    error("FX nativo no permitido")
  end
  local before_count = reaper.TrackFX_GetCount(track)
  local result = run_transaction(project, request_id, description, function()
    local fx_index = reaper.TrackFX_AddByName(track, plugin_name, false, -1)
    if fx_index < 0 then error("REAPER no pudo agregar " .. expected_name) end
    if reaper.TrackFX_GetCount(track) ~= before_count + 1 then
      error("la cantidad de FX no aumentó exactamente en uno")
    end
    local fx = read_fx(track, fx_index, true)
    if not fx.name:lower():find(expected_name, 1, true) then
      error("el FX agregado no tiene la identidad esperada")
    end
    if not fx.enabled or fx.offline then error("el FX no quedó activo y online") end
    local track_state = read_track(track, index)
    if track_state.fx_count ~= before_count + 1 then
      error("la lectura posterior de la pista no refleja el FX agregado")
    end
    return {
      project_ref = ref,
      track = track_state,
      fx = fx,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.add_master_stock_fx(params, request_id)
  local project, _, ref = require_project(params)
  local fx_type = require_string(params.fx_type, "fx_type", 32)
  if fx_type ~= "realimit" then error("FX de master no permitido") end
  local master = reaper.GetMasterTrack(project)
  if not master then error("REAPER no devolvió la pista master") end
  if count_fx_by_name_fragment(master, "realimit") > 0 then
    error("el master ya contiene ReaLimit")
  end
  local before_count = reaper.TrackFX_GetCount(master)
  local result = run_transaction(project, request_id, "agregar ReaLimit al master", function()
    local fx_index = reaper.TrackFX_AddByName(master, "ReaLimit (Cockos)", false, -1)
    if fx_index < 0 then error("REAPER no pudo agregar ReaLimit") end
    if reaper.TrackFX_GetCount(master) ~= before_count + 1 then
      error("la cantidad de FX del master no aumentó exactamente en uno")
    end
    local fx = read_fx(master, fx_index, true)
    if not fx.name:lower():find("realimit", 1, true) then
      error("el FX agregado no es ReaLimit")
    end
    if not fx.enabled or fx.offline then error("ReaLimit no quedó activo y online") end
    local state = read_track(master, -1)
    if state.fx_count ~= before_count + 1 then
      error("la lectura posterior del master no refleja ReaLimit")
    end
    return {
      project_ref = ref,
      track = state,
      fx = fx,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.apply_mastering_limiter(params, request_id)
  local project, _, ref = require_project(params)
  local proposal_id = require_string(params.proposal_id, "proposal_id", 24)
  if #proposal_id ~= 24 or not proposal_id:match("^[0-9a-f]+$") then
    error("proposal_id debe contener 24 caracteres hexadecimales minúsculos")
  end
  local source_sha256 = require_string(params.source_sha256, "source_sha256", 64)
  if #source_sha256 ~= 64 or not source_sha256:match("^[0-9a-f]+$") then
    error("source_sha256 debe contener 64 caracteres hexadecimales minúsculos")
  end
  local spec = validate_realimit_parameters(params.parameters)
  local master = reaper.GetMasterTrack(project)
  if not master then error("REAPER no devolvió la pista master") end
  local requested_guid = params.fx_guid
  local existing_index = nil
  if requested_guid ~= nil then
    requested_guid = require_string(requested_guid, "fx_guid", 64)
    existing_index = find_fx_by_guid(master, requested_guid)
    require_realimit(master, existing_index)
  elseif count_fx_by_name_fragment(master, "realimit") > 0 then
    error("el master ya contiene ReaLimit; debe vincularse mediante fx_guid")
  end

  local before_count = reaper.TrackFX_GetCount(master)
  local result = run_transaction(project, request_id, "aplicar limitador de mastering", function()
    local fx_index = existing_index
    local mode = "reuse_existing"
    if fx_index == nil then
      fx_index = reaper.TrackFX_AddByName(master, "ReaLimit (Cockos)", false, -1)
      if fx_index < 0 then error("REAPER no pudo agregar ReaLimit") end
      mode = "create_new"
    end
    local expected_count = before_count + (mode == "create_new" and 1 or 0)
    if reaper.TrackFX_GetCount(master) ~= expected_count then
      error("la cantidad de FX del master no coincide")
    end
    local fx = apply_realimit_parameters(master, fx_index, spec, requested_guid)
    local state = read_track(master, -1)
    if state.fx_count ~= expected_count then
      error("la lectura posterior del master no coincide")
    end
    return {
      project_ref = ref,
      proposal_id = proposal_id,
      source_sha256 = source_sha256,
      mode = mode,
      track = state,
      fx = fx,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.add_instrument(params, request_id)
  local project, _, ref = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  local instrument_type = require_string(params.instrument_type, "instrument_type", 32)
  local plugin_name
  local expected_name
  local description
  if instrument_type == "reasynth" then
    plugin_name, expected_name, description =
      "ReaSynth (Cockos)", "reasynth", "agregar ReaSynth"
  else
    error("instrumento virtual no permitido")
  end

  local before_count = reaper.TrackFX_GetCount(track)
  local before_instrument = reaper.TrackFX_GetInstrument(track)
  if before_instrument >= 0 then
    error("la pista ya contiene un instrumento virtual")
  end

  local result = run_transaction(project, request_id, description, function()
    local fx_index = reaper.TrackFX_AddByName(track, plugin_name, false, -1)
    if fx_index < 0 then error("REAPER no pudo agregar " .. expected_name) end
    if reaper.TrackFX_GetCount(track) ~= before_count + 1 then
      error("la cantidad de FX no aumentó exactamente en uno")
    end
    local instrument_index = reaper.TrackFX_GetInstrument(track)
    if instrument_index ~= fx_index then
      error("REAPER no reconoció el FX agregado como instrumento de la pista")
    end
    local fx = read_fx(track, fx_index, true)
    if not fx.name:lower():find(expected_name, 1, true) then
      error("el instrumento agregado no tiene la identidad esperada")
    end
    if not fx.enabled or fx.offline then
      error("el instrumento no quedó activo y online")
    end
    local track_state = read_track(track, index)
    if track_state.fx_count ~= before_count + 1 then
      error("la lectura posterior de la pista no refleja el instrumento agregado")
    end
    return {
      project_ref = ref,
      track = track_state,
      instrument = fx,
      instrument_index = instrument_index,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.configure_reaeq_band(params, request_id)
  local project, _, ref = require_project(params)
  local track = find_track_by_guid(project, params.track_guid)
  local fx_index = find_fx_by_guid(track, params.fx_guid)
  require_reaeq(track, fx_index)
  local spec = validate_reaeq_parameters(params)

  -- La API nativa dirige las bandas por tipo y ocurrencia dentro de ese tipo.
  -- Se exige que la banda exista; cambiar/agregar tipos será otra operación explícita.
  read_reaeq_band(track, fx_index, spec.band_type, spec.band_index)
  local result = run_transaction(project, request_id, "configurar banda ReaEQ", function()
    local band = apply_reaeq_parameters(track, fx_index, spec)
    return {
      project_ref = ref,
      track_guid = params.track_guid,
      fx = read_fx(track, fx_index, false),
      band = band,
      requested = {
        frequency_hz = spec.frequency_hz,
        gain_db = spec.gain_db,
        q = spec.q,
        enabled = spec.enabled,
      },
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.configure_reacomp(params, request_id)
  local project, _, ref = require_project(params)
  local track = find_track_by_guid(project, params.track_guid)
  local fx_index = find_fx_by_guid(track, params.fx_guid)
  require_reacomp(track, fx_index)
  local spec = validate_reacomp_parameters(params)

  local result = run_transaction(project, request_id, "configurar ReaComp", function()
    local fx = apply_reacomp_parameters(track, fx_index, spec, params.fx_guid)
    return {
      project_ref = ref,
      fx = fx,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.apply_processing_chain(params, request_id)
  local project, _, ref = require_project(params)
  local track, track_index = find_track_by_guid(project, params.track_guid)
  local proposal_id = require_string(params.proposal_id, "proposal_id", 24)
  if #proposal_id ~= 24 or not proposal_id:match("^[0-9a-f]+$") then
    error("proposal_id debe contener 24 caracteres hexadecimales")
  end
  local source_sha256 = require_string(params.source_sha256, "source_sha256", 64)
  if #source_sha256 ~= 64 or not source_sha256:match("^[0-9a-fA-F]+$") then
    error("source_sha256 debe ser un SHA-256 hexadecimal")
  end
  if type(params.steps) ~= "table" or #params.steps < 1 or #params.steps > 2 then
    error("steps debe contener una o dos entradas")
  end

  local validated, seen = {}, {}
  local create_count = 0
  for position, raw in ipairs(params.steps) do
    if type(raw) ~= "table" then error("cada step debe ser un objeto") end
    local processor = require_string(raw.processor, "processor", 32)
    if processor ~= "reaeq" and processor ~= "reacomp" then
      error("procesador no permitido en la propuesta")
    end
    if seen[processor] then error("procesador duplicado en la propuesta: " .. processor) end
    seen[processor] = true
    local mode = require_string(raw.mode, "mode", 32)
    if mode ~= "reuse_existing" and mode ~= "create_new" then
      error("modo de vinculación de FX no permitido")
    end
    local fragment = processor
    local plugin_name = processor == "reaeq" and "ReaEQ (Cockos)" or "ReaComp (Cockos)"
    local fx_guid = nil
    if mode == "reuse_existing" then
      fx_guid = require_string(raw.fx_guid, "fx_guid", 64)
      local fx_index = find_fx_by_guid(track, fx_guid)
      if processor == "reaeq" then
        require_reaeq(track, fx_index)
      else
        require_reacomp(track, fx_index)
      end
    else
      if raw.fx_guid ~= nil then error("create_new no admite fx_guid") end
      if count_fx_by_name_fragment(track, fragment) > 0 then
        error("la pista ya contiene " .. processor .. "; vincule su GUID para evitar duplicados")
      end
      create_count = create_count + 1
    end
    validated[position] = {
      processor = processor,
      mode = mode,
      fx_guid = fx_guid,
      plugin_name = plugin_name,
      spec = processor == "reaeq"
        and validate_reaeq_parameters(raw.parameters)
        or validate_reacomp_parameters(raw.parameters),
    }
  end

  local before_count = reaper.TrackFX_GetCount(track)
  local result = run_transaction(
    project, request_id, "aplicar propuesta " .. proposal_id, function()
      local applied = {}
      for position, step in ipairs(validated) do
        local fx_index
        if step.mode == "reuse_existing" then
          fx_index = find_fx_by_guid(track, step.fx_guid)
        else
          local count_before_add = reaper.TrackFX_GetCount(track)
          fx_index = reaper.TrackFX_AddByName(track, step.plugin_name, false, -1)
          if fx_index < 0 then error("REAPER no pudo agregar " .. step.processor) end
          if reaper.TrackFX_GetCount(track) ~= count_before_add + 1 then
            error("la cantidad de FX no aumentó exactamente en uno")
          end
          local added = read_fx(track, fx_index, false)
          if not added.name:lower():find(step.processor, 1, true) then
            error("el FX creado no tiene la identidad esperada")
          end
          if not added.enabled or added.offline then
            error("el FX creado no quedó activo y online")
          end
        end

        if step.processor == "reaeq" then
          local band = apply_reaeq_parameters(track, fx_index, step.spec)
          applied[position] = {
            processor = step.processor,
            mode = step.mode,
            fx = read_fx(track, fx_index, false),
            band = band,
          }
        else
          applied[position] = {
            processor = step.processor,
            mode = step.mode,
            fx = apply_reacomp_parameters(track, fx_index, step.spec, step.fx_guid),
          }
        end
      end
      local track_state = read_track(track, track_index)
      if track_state.fx_count ~= before_count + create_count then
        error("la lectura posterior de la pista no refleja la cadena aplicada")
      end
      return {
        project_ref = ref,
        proposal_id = proposal_id,
        source_sha256 = source_sha256,
        track = track_state,
        applied = applied,
        transaction_request_id = request_id,
      }
    end)
  return result, observations(true)
end

local function import_audio_into_new_track(project, file_path, track_name, position)
  local index = reaper.CountTracks(project)
  reaper.InsertTrackInProject(project, index, 0)
  local track = reaper.GetTrack(project, index)
  if not track then error("REAPER no devolvió la pista para importar") end
  if not reaper.GetSetMediaTrackInfo_String(track, "P_NAME", track_name, true) then
    error("REAPER rechazó el nombre de la pista")
  end
  local item = reaper.AddMediaItemToTrack(track)
  if not item then error("REAPER no pudo crear el ítem") end
  if not reaper.SetMediaItemInfo_Value(item, "C_BEATATTACHMODE", 0) then
    error("REAPER rechazó el timebase absoluto del ítem")
  end
  if not reaper.SetMediaItemInfo_Value(item, "C_AUTOSTRETCH", 0) then
    error("REAPER rechazó desactivar auto-stretch en el ítem")
  end
  local take = reaper.AddTakeToMediaItem(item)
  if not take then error("REAPER no pudo crear la toma") end
  local source = reaper.PCM_Source_CreateFromFile(file_path)
  if not source then error("REAPER no pudo abrir el WAV") end
  local source_length, length_is_qn = reaper.GetMediaSourceLength(source)
  if length_is_qn or source_length <= 0 then
    reaper.PCM_Source_Destroy(source)
    error("la fuente WAV no informó una duración válida en segundos")
  end
  if not reaper.SetMediaItemTake_Source(take, source) then
    reaper.PCM_Source_Destroy(source)
    error("REAPER no pudo asignar la fuente a la toma")
  end
  if not reaper.SetMediaItemPosition(item, position, false) then
    error("REAPER rechazó la posición del ítem")
  end
  if not reaper.SetMediaItemLength(item, source_length, false) then
    error("REAPER rechazó la duración del ítem")
  end
  local track_state = read_track(track, index)
  local item_state = read_imported_item(item, take)
  if track_state.name ~= track_name then error("el nombre leído de la pista no coincide") end
  if normalized_absolute_path(item_state.take.source_path, "source_path")
    ~= normalized_absolute_path(file_path, "file_path") then
    error("la ruta leída de la fuente no coincide")
  end
  if math.abs(item_state.position_seconds - position) > 0.000001 then
    error("la posición leída del ítem no coincide")
  end
  if math.abs(item_state.length_seconds - source_length) > 0.000001 then
    error("la duración leída del ítem no coincide")
  end
  if item_state.timebase ~= 0 or item_state.auto_stretch then
    error("el ítem importado no quedó fijado a tiempo absoluto")
  end
  return { track = track_state, item = item_state }
end

function ACTIONS.import_audio(params, request_id)
  local project, _, ref = require_project(params)
  local file_path = require_allowed_audio_path(params.file_path)
  local track_name = require_string(params.track_name, "track_name", 128)
  local position = params.position_seconds == nil
    and 0.0 or require_number(params.position_seconds, "position_seconds", 0.0)
  local result = run_transaction(project, request_id, "importar audio", function()
    local imported = import_audio_into_new_track(project, file_path, track_name, position)
    return {
      project_ref = ref,
      track = imported.track,
      item = imported.item,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.import_audio_batch(params, request_id)
  local project, _, ref = require_project(params)
  if type(params.items) ~= "table" then error("items debe ser un arreglo") end
  if #params.items < 1 or #params.items > 64 then error("items debe contener entre 1 y 64 entradas") end
  local validated, paths, names = {}, {}, {}
  for index, item in ipairs(params.items) do
    if type(item) ~= "table" then error("cada entrada de items debe ser un objeto") end
    local file_path = require_allowed_audio_path(item.file_path)
    local track_name = require_string(item.track_name, "track_name", 128)
    local position = item.position_seconds == nil
      and 0.0 or require_number(item.position_seconds, "position_seconds", 0.0)
    local normalized_path = normalized_absolute_path(file_path, "file_path")
    if paths[normalized_path] then error("items contiene un archivo duplicado") end
    if names[track_name] then error("items contiene un nombre de pista duplicado") end
    paths[normalized_path], names[track_name] = true, true
    validated[index] = { file_path = file_path, track_name = track_name, position = position }
  end
  local result = run_transaction(project, request_id, "importar lote de audio", function()
    local imports = {}
    for index, item in ipairs(validated) do
      imports[index] = import_audio_into_new_track(
        project, item.file_path, item.track_name, item.position
      )
    end
    return {
      project_ref = ref,
      imported_count = #imports,
      imports = imports,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

local function midi_note_less(left, right)
  if left.start_tick ~= right.start_tick then return left.start_tick < right.start_tick end
  if left.pitch ~= right.pitch then return left.pitch < right.pitch end
  if left.end_tick ~= right.end_tick then return left.end_tick < right.end_tick end
  if left.channel ~= right.channel then return left.channel < right.channel end
  return left.velocity < right.velocity
end

local function midi_program_less(left, right)
  if left.tick ~= right.tick then return left.tick < right.tick end
  if left.channel ~= right.channel then return left.channel < right.channel end
  return left.program < right.program
end

local function validate_midi_import_spec(value)
  if type(value) ~= "table" then error("la entrada MIDI debe ser un objeto") end
  local spec = {
    file_path = require_allowed_midi_path(value.file_path),
    source_sha256 = require_string(value.source_sha256, "source_sha256", 64),
    track_name = require_string(value.track_name, "track_name", 128),
    position_quarter_notes = require_number(
      value.position_quarter_notes, "position_quarter_notes", 0.0, 1000000.0),
    muted = require_boolean(value.muted, "muted"),
    expected_bpm = require_number(value.expected_bpm, "expected_bpm", 20.0, 400.0),
    ticks_per_beat = require_integer(value.ticks_per_beat, "ticks_per_beat", 1, 15360),
    note_count = require_integer(value.note_count, "note_count", 1, 8000),
    end_tick = require_integer(value.end_tick, "end_tick", 1, 2000000000),
    notes = {},
    program_changes = {},
  }
  if #spec.source_sha256 ~= 64 or not spec.source_sha256:match("^[0-9a-fA-F]+$") then
    error("source_sha256 debe ser un SHA-256 hexadecimal")
  end
  if type(value.notes) ~= "table" or #value.notes ~= spec.note_count then
    error("notes no coincide con note_count")
  end
  local maximum_end = 0
  for index, note in ipairs(value.notes) do
    if type(note) ~= "table" then error("cada nota MIDI debe ser un objeto") end
    local validated = {
      start_tick = require_integer(note.start_tick, "start_tick", 0, 2000000000),
      end_tick = require_integer(note.end_tick, "end_tick", 1, 2000000000),
      pitch = require_integer(note.pitch, "pitch", 0, 127),
      velocity = require_integer(note.velocity, "velocity", 1, 127),
      channel = require_integer(note.channel, "channel", 0, 15),
    }
    if validated.end_tick <= validated.start_tick then
      error("la nota " .. index .. " no tiene duración positiva")
    end
    maximum_end = math.max(maximum_end, validated.end_tick)
    spec.notes[index] = validated
  end
  if maximum_end ~= spec.end_tick then error("end_tick no coincide con las notas") end
  table.sort(spec.notes, midi_note_less)

  if type(value.program_changes) ~= "table" or #value.program_changes > 256 then
    error("program_changes debe ser un arreglo de hasta 256 eventos")
  end
  for index, event in ipairs(value.program_changes) do
    if type(event) ~= "table" then error("cada cambio de programa debe ser un objeto") end
    spec.program_changes[index] = {
      tick = require_integer(event.tick, "program_tick", 0, spec.end_tick),
      channel = require_integer(event.channel, "program_channel", 0, 15),
      program = require_integer(event.program, "program", 0, 127),
    }
  end
  table.sort(spec.program_changes, midi_program_less)
  return spec
end

local function midi_tick_from_ppq(take, ppq, position_qn, ticks_per_beat)
  local project_qn = reaper.MIDI_GetProjQNFromPPQPos(take, ppq)
  return math.floor((project_qn - position_qn) * ticks_per_beat + 0.5)
end

local function read_and_verify_midi_take(take, spec)
  local count_ok, note_count, cc_count, text_count = reaper.MIDI_CountEvts(take)
  if not count_ok then error("REAPER no pudo contar los eventos MIDI") end
  if note_count ~= #spec.notes then error("la cantidad de notas releída no coincide") end
  if cc_count ~= #spec.program_changes then
    error("la cantidad de eventos de programa releída no coincide")
  end
  if text_count ~= 0 then error("REAPER creó eventos de texto o SysEx inesperados") end

  local observed_notes = {}
  local pitch_min, pitch_max, velocity_min, velocity_max = 127, 0, 127, 0
  for index = 0, note_count - 1 do
    local ok, _, note_muted, start_ppq, end_ppq, channel, pitch, velocity =
      reaper.MIDI_GetNote(take, index)
    if not ok then error("REAPER no pudo releer la nota MIDI " .. index) end
    if note_muted then error("REAPER silenció una nota MIDI inesperadamente") end
    local note = {
      start_tick = midi_tick_from_ppq(
        take, start_ppq, spec.position_quarter_notes, spec.ticks_per_beat),
      end_tick = midi_tick_from_ppq(
        take, end_ppq, spec.position_quarter_notes, spec.ticks_per_beat),
      channel = channel,
      pitch = pitch,
      velocity = velocity,
    }
    pitch_min, pitch_max = math.min(pitch_min, pitch), math.max(pitch_max, pitch)
    velocity_min = math.min(velocity_min, velocity)
    velocity_max = math.max(velocity_max, velocity)
    observed_notes[#observed_notes + 1] = note
  end
  table.sort(observed_notes, midi_note_less)
  for index, expected in ipairs(spec.notes) do
    local observed = observed_notes[index]
    if observed.start_tick ~= expected.start_tick
      or observed.end_tick ~= expected.end_tick
      or observed.channel ~= expected.channel
      or observed.pitch ~= expected.pitch
      or observed.velocity ~= expected.velocity then
      error("la nota MIDI releída no coincide en el índice " .. index)
    end
  end

  local observed_programs = {}
  for index = 0, cc_count - 1 do
    local ok, _, event_muted, ppq, status, channel, message2 = reaper.MIDI_GetCC(take, index)
    if not ok then error("REAPER no pudo releer el evento MIDI " .. index) end
    if event_muted or status ~= 0xC0 then
      error("REAPER devolvió un evento de canal inesperado")
    end
    observed_programs[#observed_programs + 1] = {
      tick = midi_tick_from_ppq(
        take, ppq, spec.position_quarter_notes, spec.ticks_per_beat),
      channel = channel,
      program = message2,
    }
  end
  table.sort(observed_programs, midi_program_less)
  for index, expected in ipairs(spec.program_changes) do
    local observed = observed_programs[index]
    if observed.tick ~= expected.tick or observed.channel ~= expected.channel
      or observed.program ~= expected.program then
      error("el cambio de programa releído no coincide en el índice " .. index)
    end
  end
  return {
    note_count = note_count,
    program_change_count = cc_count,
    pitch_min = pitch_min,
    pitch_max = pitch_max,
    velocity_min = velocity_min,
    velocity_max = velocity_max,
    end_tick = spec.end_tick,
    ticks_per_beat = spec.ticks_per_beat,
  }
end

local function materialize_midi_into_new_track(project, spec)
  local observed_tempo = reaper.Master_GetTempo()
  if math.abs(observed_tempo - spec.expected_bpm) > 0.001 then
    error("el tempo del proyecto no coincide con el MIDI")
  end
  local index = reaper.CountTracks(project)
  reaper.InsertTrackInProject(project, index, 0)
  local track = reaper.GetTrack(project, index)
  if not track then error("REAPER no devolvió la pista MIDI creada") end
  if not reaper.GetSetMediaTrackInfo_String(track, "P_NAME", spec.track_name, true) then
    error("REAPER rechazó el nombre de la pista MIDI")
  end
  if not reaper.SetMediaTrackInfo_Value(track, "B_MUTE", spec.muted and 1 or 0) then
    error("REAPER rechazó el mute inicial de la pista MIDI")
  end

  local end_qn = spec.position_quarter_notes + spec.end_tick / spec.ticks_per_beat
  local item = reaper.CreateNewMIDIItemInProj(
    track, spec.position_quarter_notes, end_qn, true)
  if not item then error("REAPER no pudo crear el ítem MIDI") end
  if not reaper.SetMediaItemInfo_Value(item, "C_BEATATTACHMODE", 1) then
    error("REAPER rechazó el timebase musical del ítem MIDI")
  end
  local take = reaper.GetActiveTake(item)
  if not take or not reaper.TakeIsMIDI(take) then
    error("REAPER no devolvió una toma MIDI")
  end
  if not reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", spec.track_name, true) then
    error("REAPER rechazó el nombre de la toma MIDI")
  end

  for _, note in ipairs(spec.notes) do
    local start_qn = spec.position_quarter_notes + note.start_tick / spec.ticks_per_beat
    local end_note_qn = spec.position_quarter_notes + note.end_tick / spec.ticks_per_beat
    if not reaper.MIDI_InsertNote(
        take, false, false,
        reaper.MIDI_GetPPQPosFromProjQN(take, start_qn),
        reaper.MIDI_GetPPQPosFromProjQN(take, end_note_qn),
        note.channel, note.pitch, note.velocity, true) then
      error("REAPER rechazó una nota MIDI")
    end
  end
  for _, event in ipairs(spec.program_changes) do
    local event_qn = spec.position_quarter_notes + event.tick / spec.ticks_per_beat
    if not reaper.MIDI_InsertCC(
        take, false, false, reaper.MIDI_GetPPQPosFromProjQN(take, event_qn),
        0xC0, event.channel, event.program, 0) then
      error("REAPER rechazó un cambio de programa MIDI")
    end
  end
  reaper.MIDI_Sort(take)

  local item_ok, item_guid = reaper.GetSetMediaItemInfo_String(item, "GUID", "", false)
  local take_ok, take_guid = reaper.GetSetMediaItemTakeInfo_String(take, "GUID", "", false)
  if not item_ok or item_guid == "" then error("REAPER no devolvió GUID del ítem MIDI") end
  if not take_ok or take_guid == "" then error("REAPER no devolvió GUID de la toma MIDI") end
  local track_state = read_track(track, index)
  if track_state.name ~= spec.track_name or track_state.muted ~= spec.muted then
    error("la lectura posterior de la pista MIDI no coincide")
  end
  local midi = read_and_verify_midi_take(take, spec)
  return {
    source_path = spec.file_path,
    source_sha256 = spec.source_sha256,
    track = track_state,
    item = {
      guid = item_guid,
      take_guid = take_guid,
      position_quarter_notes = spec.position_quarter_notes,
      end_quarter_notes = end_qn,
      timebase = reaper.GetMediaItemInfo_Value(item, "C_BEATATTACHMODE"),
      midi = midi,
    },
  }
end

function ACTIONS.import_midi(params, request_id)
  local project, _, ref = require_project(params)
  local spec = validate_midi_import_spec(params)
  local result = run_transaction(project, request_id, "importar MIDI", function()
    local imported = materialize_midi_into_new_track(project, spec)
    return {
      project_ref = ref,
      track = imported.track,
      item = imported.item,
      source_path = imported.source_path,
      source_sha256 = imported.source_sha256,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.import_midi_batch(params, request_id)
  local project, _, ref = require_project(params)
  if type(params.items) ~= "table" or #params.items < 1 or #params.items > 8 then
    error("items debe contener entre 1 y 8 entradas MIDI")
  end
  local specs, paths, names = {}, {}, {}
  for index, item in ipairs(params.items) do
    local spec = validate_midi_import_spec(item)
    local normalized_path = normalized_absolute_path(spec.file_path, "file_path")
    if paths[normalized_path] then error("items contiene un MIDI duplicado") end
    if names[spec.track_name] then error("items contiene un nombre de pista duplicado") end
    paths[normalized_path], names[spec.track_name] = true, true
    specs[index] = spec
  end
  local result = run_transaction(project, request_id, "importar lote MIDI", function()
    local imports = {}
    for index, spec in ipairs(specs) do
      imports[index] = materialize_midi_into_new_track(project, spec)
    end
    return {
      project_ref = ref,
      imported_count = #imports,
      imports = imports,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.set_project_tempo(params, request_id)
  local project, _, ref = require_project(params)
  local bpm = require_number(params.bpm, "bpm", 20.0, 400.0)
  local before_tempo = reaper.Master_GetTempo()
  local before_items = snapshot_item_timing(project)
  local result = run_transaction(project, request_id, "ajustar tempo", function()
    local locked_items = lock_audio_items_to_time(project, before_items)
    reaper.SetCurrentBPM(project, bpm, false)
    local observed_tempo = reaper.Master_GetTempo()
    if math.abs(observed_tempo - bpm) > 0.000001 then
      error("la lectura posterior del tempo no coincide")
    end
    verify_item_timing_unchanged(project, before_items)
    return {
      project_ref = ref,
      tempo_before_bpm = before_tempo,
      tempo_bpm = observed_tempo,
      preserved_item_count = reaper.CountMediaItems(project),
      audio_items_locked_to_time = locked_items,
      transaction_request_id = request_id,
    }
  end)
  return result, observations(true)
end

function ACTIONS.save_project_as(params, _)
  local project, old_path, old_ref = require_project(params)
  local target_path = require_allowed_project_path(params.project_path)
  local target_normalized = normalized_absolute_path(target_path, "project_path")
  local saving_current = old_path ~= ""
    and normalized_absolute_path(old_path, "current_project_path") == target_normalized
  if file_exists(target_path) and not saving_current then
    error("el proyecto de destino ya existe; no se sobrescribe")
  end
  local directory = target_path:match("^(.*)[\\/][^\\/]+$")
  if not directory or directory == "" then error("project_path no contiene directorio") end
  reaper.RecursiveCreateDirectory(directory, 0)
  if saving_current then
    reaper.Main_SaveProject(project, false)
  else
    reaper.Main_SaveProjectEx(project, target_path, 8)
  end
  local observed_project, observed_path, observed_ref = project_context()
  if observed_project ~= project then error("REAPER cambió de instancia de proyecto al guardar") end
  if normalized_absolute_path(observed_path, "observed_project_path")
    ~= normalized_absolute_path(target_path, "project_path") then
    error("REAPER no adoptó la ruta nueva del proyecto")
  end
  if not file_exists(target_path) then error("REAPER no creó el archivo de proyecto") end
  return {
    previous_project_path = old_path,
    previous_project_ref = old_ref,
    project_path = observed_path,
    project_ref = observed_ref,
    track_count = reaper.CountTracks(project),
    tempo_bpm = reaper.Master_GetTempo(),
    created_new_file = not saving_current,
    saved = true,
  }, observations(true)
end

function ACTIONS.undo_transaction(params, _)
  local project, _, ref = require_project(params)
  local expected = require_string(params.transaction_request_id, "transaction_request_id", 64)
  local last_transaction = transaction_stack[#transaction_stack]
  if not last_transaction or last_transaction.request_id ~= expected then
    error("la transacción solicitada no es la última creada por este puente")
  end
  local current_label = reaper.Undo_CanUndo2(project)
  if current_label ~= last_transaction.label then
    error("el historial de REAPER cambió; no es seguro deshacer automáticamente")
  end
  local undone = reaper.Undo_DoUndo2(project)
  if undone == 0 then error("REAPER no pudo deshacer la transacción") end
  transaction_stack[#transaction_stack] = nil
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  return {
    project_ref = ref,
    undone_transaction_request_id = expected,
    project_state_change_count = reaper.GetProjectStateChangeCount(project),
  }, observations(true)
end

local function validate_request(request, filename)
  if type(request) ~= "table" then error("la solicitud debe ser un objeto") end
  if request.version ~= PROTOCOL_VERSION then error("versión de protocolo incompatible") end
  require_string(request.request_id, "request_id", 64)
  if filename ~= request.request_id .. ".json" then error("el UUID no coincide con el archivo") end
  require_string(request.action, "action", 64)
  if not ACTIONS[request.action] then error("acción no permitida: " .. request.action) end
  if type(request.params) ~= "table" then error("params debe ser un objeto") end
  require_number(request.deadline_at_ms, "deadline_at_ms")
  if os.time() * 1000 > request.deadline_at_ms then error("solicitud vencida") end
end

local function sanitize_error(value)
  local message = tostring(value):gsub("[\r\n]+", " ")
  return message:sub(1, 500)
end

local function write_response(request_id, status, result, err, observed)
  local response = {
    version = PROTOCOL_VERSION,
    request_id = request_id,
    status = status,
    completed_at_ms = os.time() * 1000,
    observations = observed or {},
  }
  if status == "ok" then response.result = result end
  if status ~= "ok" then response.error = err end
  atomic_write(join(responses_dir, request_id .. ".json"), json.encode(response))
end

local function pending_files()
  local files, index = {}, 0
  while true do
    local filename = reaper.EnumerateFiles(pending_dir, index)
    if not filename then break end
    if filename:match("^[0-9a-fA-F%-]+%.json$") then files[#files + 1] = filename end
    index = index + 1
  end
  table.sort(files)
  return files
end

local function process_one()
  for _, filename in ipairs(pending_files()) do
    local pending_path, processing_path = join(pending_dir, filename), join(processing_dir, filename)
    local claimed = os.rename(pending_path, processing_path)
    if claimed then
      local request_id = filename:gsub("%.json$", "")
      if file_exists(join(responses_dir, filename)) then
        os.remove(processing_path)
        return true
      end
      local decoded_ok, request_or_error = xpcall(function()
        return json.decode(read_file(processing_path))
      end, debug.traceback)
      if not decoded_ok then
        os.rename(processing_path, join(quarantine_dir, filename))
        return true
      end
      local request = request_or_error
      local valid_ok, validation_error = xpcall(function()
        validate_request(request, filename)
      end, debug.traceback)
      if not valid_ok then
        write_response(request_id, "rejected", {}, {
          code = "invalid_request", message = sanitize_error(validation_error),
        }, observations(false))
        os.remove(processing_path)
        return true
      end
      local action_ok, result, observed = xpcall(function()
        return ACTIONS[request.action](request.params, request.request_id)
      end, debug.traceback)
      if action_ok then
        write_response(request.request_id, "ok", result, nil, observed)
      else
        write_response(request.request_id, "error", {}, {
          code = "action_failed", message = sanitize_error(result),
        }, observations(false))
      end
      os.remove(processing_path)
      return true
    end
  end
  return false
end

local function loop()
  if reaper.GetExtState(SECTION, INSTANCE_KEY) ~= instance_token then return end
  local now = reaper.time_precise()
  if now - last_poll_at >= POLL_INTERVAL_SECONDS then
    last_poll_at = now
    local ok, err = xpcall(process_one, debug.traceback)
    if not ok then reaper.ShowConsoleMsg("PampaPilot Bridge: " .. sanitize_error(err) .. "\n") end
  end
  reaper.defer(loop)
end

ensure_directories()
reaper.SetExtState(SECTION, INSTANCE_KEY, instance_token, false)
set_action_toggle_state(true)
reaper.atexit(function()
  if reaper.GetExtState(SECTION, INSTANCE_KEY) == instance_token then
    reaper.DeleteExtState(SECTION, INSTANCE_KEY, false)
    set_action_toggle_state(false)
  end
end)
loop()
