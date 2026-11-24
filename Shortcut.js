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

function mask(chord) {
  var c = norm(chord)
  if (!c) return -1
  var parts = c.split(" + "), m = 0
  for (var i = 0; i < parts.length - 1; i++) m += MASK[parts[i]]
  return m
}

// ¿Ese atajo ya lo usa OTRA cosa? binds = salida de `hyprctl binds -j`.
function conflict(binds, chord) {
  var c = norm(chord)
  if (!c || !binds) return false
  var key = c.split(" + ").pop(), m = mask(c)
  for (var i = 0; i < binds.length; i++) {
    var b = binds[i]
    if (b.submap || b.mouse) continue
    if (b.modmask === m && String(b.key).toUpperCase() === key && b.description !== DESC) return true
  }
  return false
}

function luaStr(s) { return "[[" + String(s).replace(/\]\]/g, "] ]") + "]]" }

// Quita el anterior (si era nuestro) y pone el nuevo.
function lua(previous, chord) {
  var lines = []
  var p = norm(previous), c = norm(chord)
  if (p) lines.push("pcall(function() hl.unbind(" + luaStr(p) + ") end)")
  if (c) lines.push("hl.bind(" + luaStr(c) + ", hl.dsp.exec_cmd(" + luaStr(CMD) + "), { description = " + luaStr(DESC) + " })")
  return lines.join("; ")
}

if (typeof module !== "undefined") module.exports = { norm: norm, mask: mask, conflict: conflict, lua: lua, DESC: DESC }
