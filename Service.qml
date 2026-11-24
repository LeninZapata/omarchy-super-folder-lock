import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons as Commons
import "Watchdog.js" as Watchdog
import "Settings.js" as Settings
import "Core.js" as Core
import "Shortcut.js" as Shortcut

// Servicio del plugin: vive mientras el shell corre (keepLoaded). Lleva el estado de
// las carpetas, habla con el auxiliar (bin/folderlock.py) y expone el IPC (ESQUEMA M2).
// Aquí nunca se guarda una clave: viaja al auxiliar por stdin y se borra al enviarla.
Item {
  id: root

  // Los inyecta el shell si existen.
  property var shell: null
  property var manifest: null

  readonly property string pluginId: "leninzapata.super-folder-lock"
  readonly property string helperPath: String(Qt.resolvedUrl("bin/folderlock.py")).replace(/^file:\/\//, "")

  // ---------------------------------------------------------------- estado (DATOS.md)
  property bool windowOpen: false
  // Copia de `folderlock.py list`: solo mientras la ventana está abierta.
  property var folders: []
  property var openIds: []
  property int total: 0
  // {id: {workspaceId, openedAt}} de las carpetas abiertas desde este shell.
  property var openFolders: ({})
  property string busyId: ""
  // {id: clave i18n} del último error del auxiliar para esa fila (nunca la clave escrita).
  property var rowErrors: ({})
  property string globalError: ""

  // ---------------------------------------------------------------- puerta (ESQUEMA M3)
  // Hasta pasar la clave del sistema no se carga NADA del registro; al cerrar la ventana
  // (y al bloquear la pantalla, A6) la puerta se cierra y la lista se vacía.
  property bool gateOpen: false

  function openGate() {
    gateOpen = true
    touch()
    refresh()
  }

  function isOpen(id) { return openIds.indexOf(id) !== -1 }

  // La ventana flota centrada y sin barra de título. Va por `o.window` de Omarchy (si está):
  // así cuenta como app que flota por su cuenta y el modo «workspace flotante» no le impone su
  // tamaño (min(1100)×min(760)) ni su barra, que mostraría «Quickshell» (el nombre del .desktop
  // de org.quickshell, no el título). Se registra con `hyprctl eval` en cada open: un recargo
  // de Hyprland la borra.
  // no_screen_share solo si Lenin lo activa en ⚙ (B7): también deja en negro a grim.
  readonly property string windowRuleLua: 'local m = { title = "^Super Folder Lock$" } '
    + 'local r = { name = "super-folder-lock-window", float = true, center = true, ["hyprbars:no_bar"] = true, '
    + 'no_screen_share = ' + (settings.hideOnShare ? "true" : "false") + ' } '
    + 'if o and o.window then o.window(m, r) else r.match = m hl.window_rule(r) end'

  // Al pasar la puerta la ventana crece (puerta pequeña, listado grande). Hyprland no atiende
  // el cambio de tamaño que pide la app en una flotante ya abierta: se lo pide el servicio
  // (resize exacto) y luego la centra.
  function fitWindow(w, h) {
    var sel = 'window = "title:^Super Folder Lock$"'
    Quickshell.execDetached(["sh", "-c", 'hyprctl dispatch "$1" >/dev/null; hyprctl dispatch "$2" >/dev/null', "sfl-fit",
      'hl.dsp.window.resize({ x = ' + Math.round(w) + ', y = ' + Math.round(h) + ', ' + sel + ' })',
      'hl.dsp.window.center({ ' + sel + ' })'])
  }

  function open() {
    // Una sola ventana: si ya está abierta, se enfoca (aunque esté en otro workspace).
    if (windowOpen) {
      Quickshell.execDetached(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "title:^Super Folder Lock$" })'])
      refresh()
      return
    }
    gocryptfsProc.running = true
    ruleProc.exec(["hyprctl", "eval", windowRuleLua])
  }

  Process {
    id: ruleProc
    onExited: {
      root.gateOpen = false
      root.touch()
      root.windowOpen = true
      root.refresh()
    }
  }

  function closeWindow() {
    windowOpen = false
    gateOpen = false
    orphanIds = []
    cardId = ""
    cardName = ""
    cardAddress = ""
    cardRules = ({})
    folders = []
    rowErrors = ({})
    globalError = ""
  }

  function refresh() {
    helper(["status"], "", function(r) {
      if (r.ok) { openIds = r.data.open; total = r.data.total }
    })
    if (!windowOpen || !gateOpen) return
    helper(["list"], "", function(r) {
      if (!root.windowOpen || !root.gateOpen) return
      if (r.ok) { folders = r.data.folders; globalError = "" }
      else { folders = []; globalError = r.error }
    })
    helper(["orphans"], "", function(r) {
      if (root.windowOpen && root.gateOpen && r.ok) { orphanDisks = r.data.disks; orphanIds = r.data.ids }
    })
  }

  function setRowError(id, key) {
    var next = Object.assign({}, rowErrors)
    if (key) next[id] = key
    else delete next[id]
    rowErrors = next
  }

  function folderById(id) {
    for (var i = 0; i < folders.length; i++) if (folders[i].id === id) return folders[i]
    return null
  }

  // La clave llega del campo, viaja por stdin y no se guarda en ninguna propiedad.
  // recovery = la clave escrita es la de recuperación (gocryptfs -masterkey, verificada con el testigo).
  function unlock(id, key, recovery) {
    if (busyId !== "") return
    busyId = id
    setRowError(id, "")
    var ws = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : -1
    // Desde la tarjeta del modo visible no hay listado cargado: sus reglas vienen de `info`.
    var fromCard = id === cardId
    var rules = fromCard ? cardRules : rulesOf(folderById(id))
    helper(recovery ? ["unlock", id, "recovery"] : ["unlock", id], key, function(r) {
      root.busyId = ""
      if (!r.ok) { root.setRowError(id, r.error); return }
      var next = Object.assign({}, root.openFolders)
      // H1: copia de las reglas crudas (sin nombre ni ruta) para actuar con la puerta cerrada.
      next[id] = { workspaceId: ws, openedAt: Date.now(), rules: rules }
      root.openFolders = next
      if (root.openIds.indexOf(id) === -1) root.openIds = root.openIds.concat([id])
      root.startWatchdog()
      if (fromCard) {
        // Nautilus sigue enseñando la carpeta vacía de debajo: se cierra esa ventana y se
        // abre otra ya con el contenido.
        if (root.cardAddress !== "")
          Quickshell.execDetached(["hyprctl", "dispatch", 'hl.dsp.window.close({ window = "address:' + root.cardAddress + '" })'])
        Quickshell.execDetached(["sh", "-c", 'sleep 0.4; xdg-open "$1"', "sfl-open", r.data.path])
        root.closeWindow()
        return
      }
      // H3: abrir en el gestor y cerrar la ventana (y con ella la puerta); si la regla
      // dice que no, la ventana se queda.
      if (root.eff(rules).openInFileManager) {
        Quickshell.execDetached(["xdg-open", r.data.path])
        root.closeWindow()
      } else root.refresh()
    })
  }

  // Crear: la clave y los datos viajan por stdin (línea 1 clave, línea 2 JSON).
  function create(meta, key, cb) {
    helper(["init"], key + "\n" + JSON.stringify(meta), function(r) {
      cb(r)
      root.refresh()
    })
  }

  // Editar: nombre y reglas. Si está abierta, su copia de reglas (H1) se pone al día.
  function update(id, meta, cb) {
    helper(["update", id], JSON.stringify(meta), function(r) {
      if (r.ok && root.openFolders[id]) {
        var next = Object.assign({}, root.openFolders)
        next[id] = Object.assign({}, next[id], { rules: meta.rules })
        root.openFolders = next
      }
      cb(r)
      root.refresh()
    })
  }

  // Cambio rápido de clave: actual y nueva por stdin (nunca en argumentos).
  function changeKey(id, oldKey, newKey, cb) {
    if (busyId !== "") return
    busyId = id
    setRowError(id, "")
    helper(["passwd", id], oldKey + "\n" + newKey, function(r) {
      root.busyId = ""
      if (!r.ok) root.setRowError(id, r.error)
      cb(r)
    })
  }

  // [Ver]: reabre en el gestor una carpeta ya abierta.
  function view(id) {
    var f = folderById(id)
    if (f && isOpen(id)) Quickshell.execDetached(["xdg-open", f.path])
  }

  // ---------------------------------------------------------------- sin registrar · quitar protección (B6)
  property var orphanIds: []
  property var orphanDisks: ({})   // id -> nombre del disco externo, "" = interno
  // De una carpeta fuera del listado no se sabe el nombre: la clave dice cuál es.
  function readd(key, meta, cb) {
    helper(["readd", "any"], key + "\n" + JSON.stringify(meta), function(r) { cb(r); root.refresh() })
  }
  // Solo si sus archivos ya no existen (lo exige el auxiliar).
  function forgetFolder(id, cb) {
    helper(["forget", id], "", function(r) { if (!r.ok) root.setRowError(id, r.error); cb(r); root.refresh() })
  }
  // Quitar protección: los archivos salen a una carpeta normal (nunca se borran desde la
  // ventana). Puede tardar minutos: va en su PROPIO proceso, para que la cola del auxiliar
  // (y con ella el bloqueo automático de las demás) no espere a que acabe la copia.
  property string unprotectId: ""
  property var unprotectCb: null
  function unprotect(id, key, cb) {
    if (unprotectId !== "") return
    unprotectId = id
    unprotectCb = cb
    setRowError(id, "")
    unprotectProc.secret = key
    unprotectProc.read = false
    unprotectProc.exited_ = false
    unprotectProc.exec(["python3", "-I", helperPath, "unprotect", id])
  }
  function finishUnprotect() {
    if (!unprotectProc.read || !unprotectProc.exited_) return
    var id = unprotectId, cb = unprotectCb, r = null
    try { r = JSON.parse(String(unprotectOut.text).trim().split("\n").pop()) } catch (e) { r = null }
    if (!r || typeof r.ok !== "boolean") r = { ok: false, error: "unprotect.failed", data: null }
    unprotectId = ""
    unprotectCb = null
    if (!r.ok) setRowError(id, r.error)
    else Quickshell.execDetached(["xdg-open", r.data.path])
    if (cb) cb(r)
    refresh()
  }
  Process {
    id: unprotectProc
    property string secret: ""
    property bool read: false
    property bool exited_: false
    stdinEnabled: true
    onStarted: { write(secret + "\n"); secret = "" }
    stdout: StdioCollector {
      id: unprotectOut
      onStreamFinished: { unprotectProc.read = true; root.finishUnprotect() }
    }
    onExited: { unprotectProc.exited_ = true; root.finishUnprotect() }
  }

  // Formulario: ¿sirve esa ruta? (solo mira)
  function checkPath(path, cb) { helper(["check"], JSON.stringify({ path: path }), cb) }

  // Copiar la clave de recuperación sin ponerla en argumentos (se vería en `ps`).
  function copySecret(text) {
    copyProc.secret = text
    copyProc.exec(["sh", "-c", 'IFS= read -r k; printf %s "$k" | wl-copy --sensitive'])
  }

  Process {
    id: copyProc
    property string secret: ""
    stdinEnabled: true
    onStarted: { write(secret + "\n"); secret = "" }
  }

  function lock(id) {
    if (busyId !== "") return
    busyId = id
    helper(["lock", id], "", function(r) {
      root.busyId = ""
      root.forget(id)
      if (!r.ok) root.setRowError(id, r.error)
      root.refresh()
    })
  }

  function lockAll() {
    helper(["lockall"], "", function(r) {
      root.openFolders = ({})
      if (!r.ok) root.globalError = r.error
      root.refresh()
    })
  }

  // ---------------------------------------------------------------- reglas de cierre (A5)
  readonly property string configDir: Quickshell.env("HOME") + "/.config/omarchy/super-folder-lock"
  property bool storageReady: false
  property var settings: Settings.defaults()
  property int activeWorkspaceId: -1

  function rulesOf(f) {
    if (!f) return {}
    return { idleLock: f.idleLock, idleSeconds: f.idleSeconds, workspaceLock: f.workspaceLock,
             screenLock: f.screenLock, openInFileManager: f.openInFileManager,
             maxOpenLock: f.maxOpenLock, maxOpenSeconds: f.maxOpenSeconds }
  }
  function eff(rules) { return Settings.effective(settings, rules) }

  function applySettingsText(raw) {
    var parsed = null
    try { parsed = JSON.parse(raw && raw.trim().length > 0 ? raw : "{}") } catch (e) { parsed = null }
    // Archivo roto: valores por defecto y el archivo NO se pisa hasta el próximo cambio.
    settings = Settings.normalize(parsed)
  }

  function saveSettings(next) {
    settings = Settings.normalize(next)
    settingsFile.setText(JSON.stringify(settings, null, 2) + "\n")
    // La escritura atómica crea un archivo nuevo con la máscara por defecto (644): 600 otra vez.
    chmodTimer.restart()
  }
  Timer {
    id: chmodTimer
    interval: 400
    onTriggered: Quickshell.execDetached(["chmod", "600", root.configDir + "/settings.json"])
  }

  // Bloqueo automático: sin la guarda de busyId (no espera a la interfaz).
  function lockAuto(ids, reason) {
    for (var i = 0; i < ids.length; i++) {
      var id = ids[i]
      forget(id)
      helper(["lock", id], "", function(r) { root.refresh() })
      if (settings.notifyAutoLock) notifyLocked(id)
    }
    if (ids.length > 0) lastAutoLock = reason + ":" + ids.length
  }
  property string lastAutoLock: ""

  Process {
    id: initProc
    command: ["sh", "-c", 'mkdir -p "$1" && chmod 700 "$1" && { [ ! -e "$1/settings.json" ] || chmod 600 "$1/settings.json"; }', "sfl-init", root.configDir]
    onExited: root.storageReady = true
  }

  FileView {
    id: settingsFile
    path: root.storageReady ? root.configDir + "/settings.json" : ""
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applySettingsText(text())
    onLoadFailed: if (root.storageReady) root.applySettingsText("{}")
    onFileChanged: reload()
  }

  // Salir del workspace donde se abrió una carpeta → se bloquea en el acto.
  function syncFocus() {
    var ws = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : -1
    if (ws <= 0 || ws === activeWorkspaceId) return
    activeWorkspaceId = ws
    lockAuto(Core.lockOnWorkspace(openFolders, eff, ws), "workspace")
  }
  Connections {
    target: Hyprland
    function onFocusedWorkspaceChanged() { root.syncFocus() }
  }

  // Pantalla bloqueada (omarchy.lock / LockSigil responden `omarchy-shell lock isLocked`;
  // Hyprland no avisa): cada 2 s mientras haya algo abierto o la puerta abierta (H2).
  // Bloquea las que tengan screenLock y cierra la ventana (y con ella la puerta).
  readonly property bool screenWatch: openIds.length > 0 || windowOpen
  Timer {
    interval: 2000
    repeat: true
    running: root.screenWatch
    onTriggered: if (!screenProc.running) screenProc.exec(["omarchy-shell", "lock", "isLocked"])
  }
  Process {
    id: screenProc
    stdout: StdioCollector {
      onStreamFinished: if (text.trim() === "true") root.screenLocked()
    }
  }
  function screenLocked() {
    lockAuto(Core.lockOnScreen(openFolders, eff), "screen")
    if (windowOpen) closeWindow()
  }

  // ¿Está gocryptfs? Sin él no se puede ni crear ni abrir: la ventana lo avisa.
  property bool gocryptfsOk: true
  Process {
    id: gocryptfsProc
    command: ["sh", "-c", "command -v gocryptfs >/dev/null && command -v gocryptfs-xray >/dev/null"]
    onExited: function(code) { root.gocryptfsOk = code === 0 }
  }

  // Inactividad del equipo: IdleMonitor avisa al primer minuto quieto (el plazo mínimo);
  // desde ahí se cuenta y cada carpeta se bloquea al cumplir el suyo. Ignora inhibidores.
  readonly property var idleTargets: Core.idleTargets(openFolders, eff)
  readonly property bool idleWatch: idleTargets.length > 0
  property double idleSince: 0
  IdleMonitor {
    enabled: root.idleWatch
    timeout: Settings.IDLE_MIN
    respectInhibitors: false
    onIsIdleChanged: root.idleSince = isIdle ? Date.now() - Settings.IDLE_MIN * 1000 : 0
  }
  Timer {
    interval: 5000
    repeat: true
    triggeredOnStart: true
    running: root.idleWatch && root.idleSince > 0
    onTriggered: root.lockAuto(Core.idleDue(root.openFolders, root.eff, Date.now() - root.idleSince), "idle")
  }

  // ---------------------------------------------------------------- ⚙ completo (B7)
  // Notificación al auto-bloquear: solo el nombre (lo da `info`), nunca la ruta. Apagada por defecto.
  function notifyLocked(id) {
    helper(["info", id], "", function(r) {
      if (r.ok) Quickshell.execDetached(["notify-send", "-a", "Super Folder Lock", strings.t("plugin.name"),
                                         strings.t("notify.locked").arg(r.data.name)])
    })
  }

  function installGocryptfs() {
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation", "omarchy pkg add gocryptfs"])
  }

  // Atajo para abrir la ventana, en caliente. Si ya lo usa otra cosa, no se pisa: se avisa. Sin
  // poder leer la lista de atajos no se toca nada y se reintenta.
  property var appliedShortcuts: []
  property string shortcutConflict: ""
  function applyShortcut() { bindsProc.exec(["hyprctl", "binds", "-j"]) }
  Process {
    id: bindsProc
    stdout: StdioCollector {
      onStreamFinished: {
        var p = Shortcut.plan(root.settings.openShortcut, root.appliedShortcuts, Shortcut.owners(text))
        root.appliedShortcuts = p.applied
        if (p.retry) { shortcutRetry.restart(); return }
        root.shortcutConflict = p.conflict
        if (p.lua.length > 0) Quickshell.execDetached(["hyprctl", "eval", p.lua])
      }
    }
  }
  Timer { id: shortcutRetry; interval: 3000; onTriggered: root.applyShortcut() }
  onSettingsChanged: {
    var want = Shortcut.norm(settings.openShortcut) || ""
    if (want !== (appliedShortcuts[0] || "") || (want === "" && shortcutConflict !== "")) applyShortcut()
  }
  // Una recarga de Hyprland borra lo puesto en caliente: el atajo se vuelve a poner.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (event && event.name === "configreloaded") { root.appliedShortcuts = []; shortcutReload.restart() }
    }
  }
  Timer { id: shortcutReload; interval: 300; onTriggered: root.applyShortcut() }
  // Al descargar el plugin ya no da tiempo a leer la lista aquí: binds.py la lee y suelta el atajo
  // solo si en esa tecla no hay nada más.
  Component.onDestruction: if (appliedShortcuts.length > 0)
    Quickshell.execDetached(["python3", "-I", String(Qt.resolvedUrl("bin/binds.py")).replace(/^file:\/\//, ""), "release"].concat(appliedShortcuts))

  // ---------------------------------------------------------------- tiempo máximo (B5)
  // Desde que se abrió; «Posponer» suma 15 min. Cada 5 s mientras alguna tenga la regla.
  Timer {
    interval: 5000
    repeat: true
    running: Core.anyMaxOpen(root.openFolders, root.eff)
    onTriggered: root.lockAuto(Core.maxOpenDue(root.openFolders, root.eff, Date.now()), "maxOpen")
  }
  function postpone(id) {
    if (!openFolders[id]) return
    var next = Object.assign({}, openFolders)
    next[id] = Object.assign({}, next[id], { extraMs: (next[id].extraMs || 0) + 15 * 60 * 1000 })
    openFolders = next
    now = Date.now()
  }
  function maxOpenOn(id) { return !!openFolders[id] && eff(openFolders[id].rules).maxOpenLock }

  // ---------------------------------------------------------------- la puerta caduca (B5)
  // Tras gateTimeoutSeconds sin tocar la ventana, la puerta se cierra y la lista se vacía.
  property double lastActivity: 0
  function touch() { lastActivity = Date.now() }
  Timer {
    interval: 5000
    repeat: true
    running: root.windowOpen && root.gateOpen
    onTriggered: if (Core.gateExpired(root.lastActivity, Date.now(), root.settings.gateTimeoutSeconds)) root.closeGate()
  }
  function closeGate() {
    gateOpen = false
    folders = []
    orphanIds = []
    holders = ({})
  }

  // ---------------------------------------------------------------- en uso y cuenta atrás (B4)
  // {id: [programas]} de las abiertas, solo con la ventana abierta tras la puerta.
  property var holders: ({})
  property double now: Date.now()
  Timer {
    interval: 4000
    repeat: true
    triggeredOnStart: true
    running: root.windowOpen && root.gateOpen && root.openIds.length > 0
    onTriggered: root.refreshHolders()
  }
  Timer {
    interval: 1000
    repeat: true
    running: root.windowOpen && root.openIds.length > 0
    onTriggered: root.now = Date.now()
  }
  function refreshHolders() {
    for (var i = 0; i < openIds.length; i++) {
      (function(id) {
        root.helper(["holders", id], "", function(r) {
          if (!r.ok) return
          var next = Object.assign({}, root.holders)
          next[id] = r.data.apps
          root.holders = next
        })
      })(openIds[i])
    }
  }
  function closeIn(id) { return Core.closeIn(openFolders[id], eff, now, idleSince) }

  function forget(id) {
    var next = Object.assign({}, openFolders)
    delete next[id]
    openFolders = next
    openIds = openIds.filter(function(x) { return x !== id })
  }

  // ---------------------------------------------------------------- auxiliar
  // Una llamada a la vez, en cola. Cada una: argumentos fijos, clave (si hay) por stdin,
  // una línea JSON de vuelta. El siguiente arranca cuando el anterior salió y su salida
  // terminó de leerse.
  property var queue: []
  property var currentCall: null
  property bool callExited: false
  property bool callRead: false

  function helper(args, secret, cb) {
    queue = queue.concat([{ args: args, secret: secret || "", cb: cb }])
    pump()
  }

  function pump() {
    if (currentCall !== null || queue.length === 0) return
    currentCall = queue[0]
    queue = queue.slice(1)
    callExited = false
    callRead = false
    helperProc.secret = currentCall.secret
    currentCall.secret = ""
    helperProc.exec(["python3", "-I", helperPath].concat(currentCall.args))
  }

  function finishCall(text) {
    var call = currentCall
    var r = null
    try { r = JSON.parse(String(text).trim().split("\n").pop()) } catch (e) { r = null }
    if (!r || typeof r.ok !== "boolean") r = { ok: false, error: "internal", data: null }
    currentCall = null
    if (call && call.cb) call.cb(r)
    pump()
  }

  Process {
    id: helperProc
    property string secret: ""
    stdinEnabled: true
    onStarted: {
      if (secret.length > 0) write(secret + "\n")
      secret = ""
    }
    stdout: StdioCollector {
      id: helperOut
      onStreamFinished: {
        root.callRead = true
        if (root.callExited) root.finishCall(text)
      }
    }
    onExited: {
      root.callExited = true
      if (root.callRead) root.finishCall(helperOut.text)
    }
  }

  // ---------------------------------------------------------------- vigía y arranque
  // Todo empieza bloqueado: al arrancar, lockall de lo que haya quedado montado (un shell
  // anterior que murió). Luego se averigua el PID del shell para el vigía.
  readonly property string runDir: (Quickshell.env("XDG_RUNTIME_DIR") || "/run/user/1000") + "/super-folder-lock"
  property int shellPid: 0

  function startWatchdog() {
    var cmd = Watchdog.command(shellPid, helperPath, runDir)
    if (cmd) Quickshell.execDetached(cmd)
  }

  Process {
    id: pidProc
    command: ["sh", "-c", "echo $PPID"]
    stdout: StdioCollector {
      onStreamFinished: root.shellPid = parseInt(text.trim(), 10) || 0
    }
  }

  // Si el vigía muere, vuelve a nacer (flock evita duplicados).
  Timer {
    interval: 30000
    repeat: true
    running: root.openIds.length > 0
    onTriggered: root.startWatchdog()
  }

  // ---------------------------------------------------------------- modo visible (M6)
  // bin/visiblewatch.py vigila las carpetas VISIBLES bloqueadas (lee el registro él mismo) y
  // escribe «open <id> <address>» cuando Nautilus entra en una. Aquí solo llegan ids.
  readonly property string watchPath: String(Qt.resolvedUrl("bin/visiblewatch.py")).replace(/^file:\/\//, "")
  property string lastVisibleRequest: ""
  signal visibleRequested(string id, string address)

  // Tarjeta del modo visible: SOLO esa carpeta (nombre + clave), sin puerta ni listado.
  property string cardId: ""
  property string cardName: ""
  property string cardAddress: ""
  property var cardRules: ({})
  property string cardType: "encrypt"
  onVisibleRequested: function(id, address) {
    // Al montar, gocryptfs abre la carpeta con la ventana de Nautilus aún encima: eso no es
    // otro doble clic. Se ignora la que se está abriendo, la ya abierta y la de la tarjeta.
    if (isOpen(id) || busyId === id || cardId === id || (windowOpen && cardId === "")) return
    helper(["info", id], "", function(r) {
      if (!r.ok || root.isOpen(id)) return
      root.cardId = id
      root.cardName = r.data.name
      root.cardAddress = address
      root.cardType = r.data.type
      root.cardRules = root.rulesOf(r.data)
      root.setRowError(id, "")
      if (root.windowOpen) Quickshell.execDetached(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "title:^Super Folder Lock$" })'])
      else ruleProc.exec(["hyprctl", "eval", root.windowRuleLua])
    })
  }

  Process {
    id: watchProc
    command: ["python3", "-I", root.watchPath]
    stdout: SplitParser {
      onRead: function(line) {
        var m = String(line).match(/^open ([0-9a-f]{16}) (\S*)$/)
        if (!m) return
        root.lastVisibleRequest = m[1]
        root.visibleRequested(m[1], m[2])
      }
    }
    // Si muere (o falta python), se relanza a los 5 s.
    onExited: watchRestart.restart()
  }
  Timer { id: watchRestart; interval: 5000; onTriggered: watchProc.running = true }

  // ---------------------------------------------------------------- lanzador (M2.T7)
  // Entrada «Super Folder Lock» en el lanzador de apps: se escribe al arrancar si falta o
  // cambió. No lleva datos privados; Exec abre la ventana por IPC.
  readonly property string desktopPath: (Quickshell.env("XDG_DATA_HOME") || (Quickshell.env("HOME") + "/.local/share"))
    + "/applications/leninzapata-super-folder-lock.desktop"
  readonly property string desktopText: "[Desktop Entry]\nType=Application\nName=Super Folder Lock\n"
    + "Comment=Encrypted folders behind your password\n"
    + "Exec=omarchy-shell leninzapata.super-folder-lock open\nIcon=folder-locked\nTerminal=false\n"
    + "Categories=Utility;Security;\nNoDisplay=false\n"
  FileView {
    id: desktopFile
    path: root.desktopPath
    printErrors: false
    onLoaded: if (text() !== root.desktopText) setText(root.desktopText)
    onLoadFailed: setText(root.desktopText)
  }

  Component.onCompleted: {
    watchProc.running = true
    initProc.running = true
    activeWorkspaceId = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : -1
    pidProc.running = true
    helper(["lockall"], "", function(r) { root.refresh() })
  }

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
  readonly property var translations: strings

  VaultWindow {
    service: root
    strings: strings
    visible: root.windowOpen
    onVisibleChanged: if (!visible && root.windowOpen) root.closeWindow()
  }

  // IPC: omarchy-shell leninzapata.super-folder-lock <fn>
  // Es también la puerta de las autopruebas (PLAN.md §1 Accesos). `status` nunca
  // devuelve nombres ni rutas.
  Commons.ShellIpc {
    target: root.pluginId

    function open(): string { root.open(); return "ok" }
    function close(): string { root.closeWindow(); return "ok" }
    function lockAll(): string { root.lockAll(); return "ok" }
    // Lo mismo que si se bloqueara la pantalla: solo puede BLOQUEAR (pruebas sin cerrar la sesión).
    function screenLocked(): string { root.screenLocked(); return "ok" }

    function status(): string {
      return JSON.stringify({
        version: root.manifest && root.manifest.version ? root.manifest.version : "",
        open: root.openIds.length,
        total: root.total,
        windowOpen: root.windowOpen,
        busy: root.busyId !== "",
        shellPid: root.shellPid,
        gateOpen: root.gateOpen,
        listed: root.folders.length,
        idleTargets: root.idleTargets,
        idleSince: root.idleSince,
        lastAutoLock: root.lastAutoLock,
        screenWatch: root.screenWatch,
        gocryptfsOk: root.gocryptfsOk,
        showBarIcon: root.settings.showBarIcon,
        watcher: watchProc.running,
        lastVisibleRequest: root.lastVisibleRequest !== "",
        card: root.cardId !== "",
        gateTimeout: root.settings.gateTimeoutSeconds,
        shortcut: root.appliedShortcuts[0] || "",
        shortcutConflict: root.shortcutConflict
      })
    }
  }
}
