.pragma library
// Lógica pura del servicio (sin QML): se prueba con node (tests/test-core.mjs).

// Salida de `faillock --user <u>`: cuántos fallos válidos (V) cuentan y cuánto falta
// para poder volver a intentar. deny/unlockSec = los de /etc/pam.d/omarchy-lock-password.
function faillockInfo(text, nowMs, deny, unlockSec) {
  var times = []
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var m = lines[i].match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\s+\S+\s+.*\s(V)\s*$/)
    if (!m) continue
    times.push(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime())
  }
  times.sort(function(a, b) { return a - b })
  var wait = 0
  if (times.length >= deny) {
    var left = Math.ceil((times[times.length - 1] + unlockSec * 1000 - nowMs) / 1000)
    wait = left > 0 ? left : 0
  }
  return { failures: times.length, left: Math.max(0, deny - times.length), wait: wait }
}

// ---- reglas de cierre. open = openFolders {id: {workspaceId, openedAt, rules}}; eff(rules)
// = la regla efectiva (Settings.effective ya ligada a los ajustes actuales).

// Al pasar al workspace `newWs`: las abiertas con workspaceLock cuyo workspace era otro.
function lockOnWorkspace(open, eff, newWs) {
  var ids = []
  for (var id in open) {
    var o = open[id]
    if (o && o.workspaceId > 0 && o.workspaceId !== newWs && eff(o.rules).workspaceLock) ids.push(id)
  }
  return ids.sort()
}

// Plazos de inactividad que hay que vigilar (segundos, sin repetir, de menor a mayor).
function idleTargets(open, eff) {
  var seen = {}
  for (var id in open) {
    var e = eff(open[id] && open[id].rules)
    if (e.idleLock) seen[e.idleSeconds] = true
  }
  return Object.keys(seen).map(Number).sort(function(a, b) { return a - b })
}

// Llevamos `idleMs` sin teclado ni ratón: las que ya cumplieron su plazo.
function idleDue(open, eff, idleMs) {
  var ids = []
  for (var id in open) {
    var e = eff(open[id] && open[id].rules)
    if (e.idleLock && idleMs >= e.idleSeconds * 1000) ids.push(id)
  }
  return ids.sort()
}

// Se bloqueó la pantalla: las abiertas con screenLock.
function lockOnScreen(open, eff) {
  var ids = []
  for (var id in open) if (eff(open[id] && open[id].rules).screenLock) ids.push(id)
  return ids.sort()
}

// Segundos hasta que una carpeta abierta se cierre sola por una regla de tiempo, o -1.
// La de inactividad solo cuenta si ya llevamos tiempo quietos (idleSince > 0).
function closeIn(entry, eff, nowMs, idleSince) {
  if (!entry) return -1
  var e = eff(entry.rules)
  var best = -1
  if (e.idleLock && idleSince > 0) best = Math.max(0, Math.ceil((idleSince + e.idleSeconds * 1000 - nowMs) / 1000))
  if (e.maxOpenLock) {
    var m = Math.max(0, Math.ceil((maxOpenDeadline(entry, e) - nowMs) / 1000))
    best = best < 0 ? m : Math.min(best, m)
  }
  return best
}

// Tiempo máximo abierta: desde que se abrió + lo pospuesto («Posponer» suma extraMs).
function maxOpenDeadline(entry, e) {
  return (entry.openedAt || 0) + e.maxOpenSeconds * 1000 + (entry.extraMs || 0)
}

function maxOpenDue(open, eff, nowMs) {
  var ids = []
  for (var id in open) {
    var e = eff(open[id] && open[id].rules)
    if (e.maxOpenLock && nowMs >= maxOpenDeadline(open[id], e)) ids.push(id)
  }
  return ids.sort()
}

function anyMaxOpen(open, eff) {
  for (var id in open) if (eff(open[id] && open[id].rules).maxOpenLock) return true
  return false
}

// La puerta se vuelve a cerrar tras `timeoutSec` sin usar la ventana.
function gateExpired(lastActivityMs, nowMs, timeoutSec) {
  return lastActivityMs > 0 && nowMs - lastActivityMs >= timeoutSec * 1000
}

if (typeof module !== "undefined") module.exports = { closeIn: closeIn, maxOpenDue: maxOpenDue, anyMaxOpen: anyMaxOpen, gateExpired: gateExpired, faillockInfo: faillockInfo, lockOnWorkspace: lockOnWorkspace, idleTargets: idleTargets, idleDue: idleDue, lockOnScreen: lockOnScreen }
