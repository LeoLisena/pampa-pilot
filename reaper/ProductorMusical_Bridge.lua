-- Productor Musical: puente local y verificable para REAPER.
-- El script sólo ejecuta las acciones registradas en ACTIONS.

local BRIDGE_VERSION = "0.1.0"
local PROTOCOL_VERSION = "0.1"
local MAX_MESSAGE_BYTES = 1000000
local POLL_INTERVAL_SECONDS = 0.05
local SECTION = "ProductorMusicalBridge"
local INSTANCE_KEY = "active_instance"

local separator = package.config:sub(1, 1)
local source = debug.getinfo(1, "S").source
local script_path = source:sub(1, 1) == "@" and source:sub(2) or source
local script_dir = script_path:match("^(.*[\\/])") or ("." .. separator)
local json = dofile(script_dir .. "vendor" .. separator .. "json.lua")

local function configured_ipc_root()
  local config_path = script_dir .. "bridge_config.local.json"
  local stream = io.open(config_path, "rb")
  if not stream then
    return reaper.GetResourcePath() .. separator .. "ProductorMusical" .. separator .. "ipc"
  end
  local content = stream:read("*a")
  stream:close()
  local config = json.decode(content)
  if type(config) ~= "table" or type(config.ipc_root) ~= "string" or config.ipc_root == "" then
    error("bridge_config.local.json no contiene ipc_root válido")
  end
  return config.ipc_root
end

local ipc_root = configured_ipc_root()
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
  return {
    guid = reaper.GetTrackGUID(track),
    index = index,
    name = name or "",
    volume = reaper.GetMediaTrackInfo_Value(track, "D_VOL"),
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

local function observations(state_verified)
  return {
    accepted = true,
    state_verified = state_verified == true,
    signal_verified = false,
    perceptually_evaluated = false,
  }
end

local function run_transaction(project, request_id, description, callback)
  local label = "Productor Musical: " .. description .. " [" .. request_id .. "]"
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
    project_state_change_count = reaper.GetProjectStateChangeCount(project),
    tracks = tracks,
  }, observations(true)
end

function ACTIONS.get_track_state(params, _)
  local project = require_project(params)
  local track, index = find_track_by_guid(project, params.track_guid)
  return { track = read_track(track, index) }, observations(true)
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
    if not ok then reaper.ShowConsoleMsg("Productor Musical Bridge: " .. sanitize_error(err) .. "\n") end
  end
  reaper.defer(loop)
end

ensure_directories()
reaper.SetExtState(SECTION, INSTANCE_KEY, instance_token, false)
reaper.atexit(function()
  if reaper.GetExtState(SECTION, INSTANCE_KEY) == instance_token then
    reaper.DeleteExtState(SECTION, INSTANCE_KEY, false)
  end
end)
reaper.ShowConsoleMsg("Productor Musical Bridge " .. BRIDGE_VERSION .. " iniciado.\n")
loop()
