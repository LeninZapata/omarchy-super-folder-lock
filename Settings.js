.pragma library
// Ajustes generales (~/.config/omarchy/super-folder-lock/settings.json, DATOS.md) y la
// regla EFECTIVA de una carpeta: sus reglas crudas ("inherit" | "off" | "on") resueltas
// contra los valores por defecto. Puro, se prueba con node (tests/test-settings.mjs).

var RULES = ["idleLock", "workspaceLock", "screenLock", "openInFileManager", "maxOpenLock", "closeApps"]
var IDLE_MIN = 60
var IDLE_MAX = 7200
var MAX_OPEN_MIN = 300
var MAX_OPEN_MAX = 86400
// Cerrar lo abierto de la carpeta, tanto después de bloquearla (2026-11-27).
var CLOSE_MIN = 60
var CLOSE_MAX = 86400
var GATE_MIN = 30
var GATE_MAX = 3600
var TOP_BOOLS = ["showBarIcon", "showOpenDot", "notifyAutoLock", "hideOnShare"]

function defaults() {
  return {
    schemaVersion: 1,
    showBarIcon: true,
    gateTimeoutSeconds: 120,
    openShortcut: "",
    showOpenDot: false,
    notifyAutoLock: false,
    hideOnShare: false,
    defaults: { idleLock: "on", idleSeconds: 600, workspaceLock: "on", screenLock: "on", openInFileManager: "on",
                maxOpenLock: "off", maxOpenSeconds: 3600, closeApps: "off", closeAppsSeconds: 1800 }
  }
}

function validSeconds(v, min, max) {
  min = min === undefined ? IDLE_MIN : min
  max = max === undefined ? IDLE_MAX : max
  return typeof v === "number" && Math.floor(v) === v && v >= min && v <= max
}

// Un valor desconocido o fuera de rango cae a su defecto; las claves desconocidas se van.
function normalize(raw) {
  var d = defaults()
  if (!raw || typeof raw !== "object") return d
  for (var b = 0; b < TOP_BOOLS.length; b++)
    if (typeof raw[TOP_BOOLS[b]] === "boolean") d[TOP_BOOLS[b]] = raw[TOP_BOOLS[b]]
  // El atajo se valida de verdad en Shortcut.norm; aquí solo se descarta lo que no es texto.
  if (typeof raw.openShortcut === "string" && /^[A-Za-z0-9 +]{0,40}$/.test(raw.openShortcut)) d.openShortcut = raw.openShortcut
  var rd = raw.defaults && typeof raw.defaults === "object" ? raw.defaults : {}
  for (var i = 0; i < RULES.length; i++) {
    var k = RULES[i]
    if (rd[k] === "on" || rd[k] === "off") d.defaults[k] = rd[k]
  }
  if (validSeconds(rd.idleSeconds)) d.defaults.idleSeconds = rd.idleSeconds
  if (validSeconds(rd.maxOpenSeconds, MAX_OPEN_MIN, MAX_OPEN_MAX)) d.defaults.maxOpenSeconds = rd.maxOpenSeconds
  if (validSeconds(rd.closeAppsSeconds, CLOSE_MIN, CLOSE_MAX)) d.defaults.closeAppsSeconds = rd.closeAppsSeconds
  if (validSeconds(raw.gateTimeoutSeconds, GATE_MIN, GATE_MAX)) d.gateTimeoutSeconds = raw.gateTimeoutSeconds
  return d
}

// rules = las crudas de la carpeta (copia en openFolders). Devuelve booleanos + segundos.
function effective(settings, rules) {
  var s = settings && settings.defaults ? settings : defaults()
  var r = rules || {}
  var out = {}
  for (var i = 0; i < RULES.length; i++) {
    var k = RULES[i]
    var v = r[k] === "on" || r[k] === "off" ? r[k] : s.defaults[k]
    out[k] = v === "on"
  }
  out.idleSeconds = validSeconds(r.idleSeconds) ? r.idleSeconds : s.defaults.idleSeconds
  out.maxOpenSeconds = validSeconds(r.maxOpenSeconds, MAX_OPEN_MIN, MAX_OPEN_MAX) ? r.maxOpenSeconds : s.defaults.maxOpenSeconds
  out.closeAppsSeconds = validSeconds(r.closeAppsSeconds, CLOSE_MIN, CLOSE_MAX) ? r.closeAppsSeconds : s.defaults.closeAppsSeconds
  return out
}

function withDefault(settings, key, value) {
  var next = normalize(JSON.parse(JSON.stringify(settings || defaults())))
  if (TOP_BOOLS.indexOf(key) !== -1) next[key] = !!value
  else if (key === "gateTimeoutSeconds" || key === "openShortcut") next[key] = value
  else next.defaults[key] = value
  return normalize(next)
}

if (typeof module !== "undefined") module.exports = { defaults: defaults, normalize: normalize, effective: effective, withDefault: withDefault, IDLE_MIN: IDLE_MIN, MAX_OPEN_MIN: MAX_OPEN_MIN, CLOSE_MIN: CLOSE_MIN }
