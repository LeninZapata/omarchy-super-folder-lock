.pragma library
// Atajo para abrir la ventana (ESQUEMA M2.T8.S1): se registra en caliente con `hyprctl eval`
// (nunca en bindings.lua) y se vuelve a poner tras `configreloaded`. Puro: tests/test-shortcut.mjs.

var DESC = "Super Folder Lock"
var CMD = "omarchy-shell leninzapata.super-folder-lock open"
var MASK = { SUPER: 64, CTRL: 4, ALT: 8, SHIFT: 1 }

// "super+ctrl  + k" → "SUPER + CTRL + K"; null si no vale (hace falta un modificador y una tecla).
function norm(chord) {
  if (typeof chord !== "string") return null
  var t = chord.toUpperCase().split(/[\s+]+/).filter(function(x) { return x.length > 0 })
  if (t.length < 2) return null
  var mods = [], key = t[t.length - 1]
  if (MASK[key] || !/^[A-Z0-9]+$/.test(key)) return null
  var order = ["SUPER", "CTRL", "ALT", "SHIFT"]
  for (var i = 0; i < t.length - 1; i++) if (!MASK[t[i]]) return null
  for (var j = 0; j < order.length; j++) if (t.indexOf(order[j]) !== -1 && t.indexOf(order[j]) < t.length - 1) mods.push(order[j])
  return mods.concat([key]).join(" + ")
}

// `hyprctl binds -j` → { "SUPER + K": { own: n, foreign: n } }, contando TODOS los submaps:
// hl.unbind quita la tecla de todos, así que un atajo ajeno en cualquiera la hace ajena. El dueño
// se reconoce por la descripción (DESC). null si la lista no se pudo leer.
function owners(text) {
  var list
  try { list = JSON.parse(text) } catch (e) { return null }
  if (!Array.isArray(list)) return null
  var map = {}
  for (var i = 0; i < list.length; i++) {
    var b = list[i]
    if (!b || b.mouse) continue
    var mods = []
    for (var m in MASK) if ((Number(b.modmask) || 0) & MASK[m]) mods.push(m)
    var key = String(b.key || "")
    // Omarchy ata los números por código de tecla (code:10 = «1» … code:19 = «0»).
    if (key === "" && b.keycode >= 10 && b.keycode <= 19) key = String((b.keycode - 9) % 10)
    var c = norm(mods.concat([key]).join(" + "))
    if (!c) continue
    var e = map[c] || (map[c] = { own: 0, foreign: 0 })
    if (b.description === DESC) e.own++
    else e.foreign++
  }
  return map
}

function luaStr(s) { return "[[" + String(s).replace(/\]\]/g, "] ]") + "]]" }

// Pone `chord` y suelta los `previous`, tocando solo teclas que son NUESTRAS y de nadie más
// (`own` = owners(), leído justo antes). Sin lista no se toca nada y `retry` pide repetir.
// Devuelve { lua, applied, conflict, retry }.
function plan(chord, previous, own) {
  var prev = (previous || []).map(norm).filter(function(x) { return x !== null })
  var c = norm(chord)
  if (!own) return { lua: "", applied: prev, conflict: "", retry: true }
  var lines = [], applied = [], conflict = ""
  for (var i = 0; i < prev.length; i++) {
    var o = own[prev[i]]
    if (prev[i] === c || !o || o.own === 0 || o.foreign > 0) continue
    lines.push("pcall(function() hl.unbind(" + luaStr(prev[i]) + ") end)")
  }
  if (c) {
    var w = own[c] || { own: 0, foreign: 0 }
    if (w.foreign > 0) conflict = c
    else {
      if (w.own > 0) lines.push("pcall(function() hl.unbind(" + luaStr(c) + ") end)")
      lines.push("hl.bind(" + luaStr(c) + ", hl.dsp.exec_cmd(" + luaStr(CMD) + "), { description = " + luaStr(DESC) + " })")
      applied.push(c)
    }
  }
  return { lua: lines.join("; "), applied: applied, conflict: conflict, retry: false }
}

if (typeof module !== "undefined") module.exports = { norm: norm, owners: owners, plan: plan, DESC: DESC }
