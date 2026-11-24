import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Settings.js" as Settings

// Ventana flotante de Super Folder Lock (ESQUEMA M4): el listado de carpetas con su
// estado y, en la fila, el desbloqueo en línea (como Cryptomator, REF-3). No guarda
// nada: cada acción va al servicio. Ningún TextInput: la clave va en PasswordField.
FloatingWindow {
  id: win

  property var service: null
  property var strings: null

  // ------------------------------------------------------------------ tema (piel de SWL)
  readonly property color bg: Color.menu.background
  readonly property color fg: Color.menu.text
  readonly property color accent: Color.accent
  readonly property color mutedFg: Util.alpha(fg, 0.55)
  readonly property color lineColor: Util.alpha(fg, 0.14)
  readonly property color chipBg: Util.alpha(fg, 0.07)
  readonly property color openColor: "#98c379"
  readonly property color errorColor: "#e06c75"
  readonly property string fontFamily: Style.font.menuFamily
  readonly property int margin: Style.spacing.panelPadding

  // ------------------------------------------------------------------ estado
  readonly property var folders: service ? service.folders : []
  property int cursor: 0
  // id de la fila expandida con el campo de clave ("" = ninguna)
  property string expandedId: ""

  title: t("window.title")
  color: bg
  // La puerta es pequeña; el listado y los formularios, más grandes.
  implicitWidth: gated || carded ? 560 : 808
  implicitHeight: gated || carded ? 500 : 762

  function t(key) { return strings ? strings.t(key) : key }
  function isOpen(id) { return service ? service.isOpen(id) : false }
  function current() { return folders.length > 0 ? folders[Math.min(cursor, folders.length - 1)] : null }

  function shortPath(p) {
    var home = Quickshell.env("HOME")
    return p && home && p.indexOf(home + "/") === 0 ? "~" + p.slice(home.length) : (p || "")
  }

  // Fila expandida: "unlock" (clave para abrir) o "passwd" (cambio rápido de clave).
  property string expandMode: "unlock"
  function expand(id, mode) {
    if (service) service.setRowError(id, "")
    expandMode = mode
    expandedId = id
  }

  function activate(f) {
    if (!f) return
    if (isOpen(f.id)) { service.view(f.id); return }
    expand(f.id, "unlock")
  }

  function openEdit(f) {
    if (!f) return
    expandedId = ""
    page = "edit"
    form.loadEdit(f)
  }

  // «1 carpeta cifrada fuera de la lista (en un disco)»: el disco sí se sabe; su nombre se olvidó.
  function orphanTitle() {
    if (!service || service.orphanIds.length === 0) return ""
    var names = []
    for (var i = 0; i < service.orphanIds.length; i++) {
      var d = service.orphanDisks[service.orphanIds[i]]
      if (d && names.indexOf(d) === -1) names.push(d)
    }
    var n = service.orphanIds.length
    return t(n === 1 ? "orphans.one" : "orphans.many").arg(n) + (names.length > 0 ? " (" + names.join(", ") + ")" : "")
  }

  function openReadd(id) {
    expandedId = ""
    page = "readd"
    form.loadReadd(id)
  }

  function submitReadd(id, meta, key, cb) {
    service.readd(id, key, meta, function(r) {
      cb(r)
      if (r.ok) win.backToList()
    })
  }

  function submitEdit(id, meta, cb) {
    service.update(id, meta, function(r) {
      cb(r)
      if (r.ok) win.backToList()
    })
  }

  function collapse() {
    expandedId = ""
    keys.forceActiveFocus()
  }


  // ---- páginas: "list" · "create" · "recovery" (la clave de recuperación, UNA vez)
  property string page: "list"
  // Tarjeta del modo visible: una sola carpeta, sin puerta ni listado.
  readonly property bool carded: !!service && service.cardId !== ""
  readonly property bool gated: !!service && !service.gateOpen && !carded
  property string recoveryKey: ""
  property string recoveryName: ""
  property bool copied: false

  function openCreate() {
    expandedId = ""
    page = "create"
    form.reset()
  }

  function openSettings() {
    capturing = false
    expandedId = ""
    page = "settings"
    Qt.callLater(function() { settingsPage.forceActiveFocus() })
  }

  // ⚙: cada cambio se guarda en el acto (settings.json vía el servicio).
  readonly property var settings: service ? service.settings : Settings.defaults()
  function setDefault(key, value) { service.saveSettings(Settings.withDefault(settings, key, value)) }
  readonly property var steps: ({
    idleLock: { key: "idleSeconds", list: [60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200] },
    maxOpenLock: { key: "maxOpenSeconds", list: [300, 600, 900, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 28800, 43200, 86400] },
    gateTimeoutSeconds: { key: "gateTimeoutSeconds", list: [30, 60, 120, 300, 600, 1800, 3600] }
  })
  function stepSetting(which, dir) {
    var st = steps[which]
    var cur = st.key === "gateTimeoutSeconds" ? settings.gateTimeoutSeconds : settings.defaults[st.key]
    var i = st.list.indexOf(cur)
    if (i === -1) i = Math.floor(st.list.length / 2)
    setDefault(st.key, st.list[Math.max(0, Math.min(st.list.length - 1, i + dir))])
  }
  function fmtSec(sec) {
    if (sec < 60) return sec + " s"
    if (sec >= 3600 && sec % 3600 === 0) return t("form.hours").arg(sec / 3600)
    return t("form.minutes").arg(Math.round(sec / 60))
  }
  // ⚙ atajo: se captura pulsándolo (como Super Workspace Lock).
  property bool capturing: false
  function chordFromEvent(event) {
    var key = ""
    if (event.key >= Qt.Key_F1 && event.key <= Qt.Key_F12) key = "F" + (event.key - Qt.Key_F1 + 1)
    else if (event.key >= Qt.Key_A && event.key <= Qt.Key_Z) key = String.fromCharCode(event.key)
    else if (event.key >= Qt.Key_0 && event.key <= Qt.Key_9) key = String.fromCharCode(event.key)
    if (!key) return ""
    var mods = []
    if (event.modifiers & Qt.MetaModifier) mods.push("SUPER")
    if (event.modifiers & Qt.ControlModifier) mods.push("CTRL")
    if (event.modifiers & Qt.AltModifier) mods.push("ALT")
    if (event.modifiers & Qt.ShiftModifier) mods.push("SHIFT")
    return mods.length === 0 ? "" : mods.concat([key]).join(" + ")
  }

  function backToList() {
    page = "list"
    recoveryKey = ""
    copied = false
    Qt.callLater(function() { keys.forceActiveFocus() })
  }

  function submitCreate(meta, key, cb) {
    service.create(meta, key, function(r) {
      cb(r)
      if (!r.ok) return
      if (!r.data.recoveryKey) { win.backToList(); return }   // esconder: no hay clave de recuperación
      win.recoveryName = r.data.name
      win.recoveryKey = r.data.recoveryKey
      win.copied = false
      win.page = "recovery"
      Qt.callLater(function() { recoveryPage.forceActiveFocus() })
    })
  }

  onVisibleChanged: {
    if (!visible) { expandedId = ""; page = "list"; recoveryKey = ""; gateView.reset(); cardField.clear(); cardField.useRecovery = false; return }
    cursor = 0
    Qt.callLater(function() { if (win.carded) cardField.forceActiveFocus(); else if (win.gated) gateView.focusField(); else keys.forceActiveFocus() })
  }

  onCardedChanged: {
    if (visible) recenterTimer.restart()
    if (carded && visible) Qt.callLater(function() { cardField.forceActiveFocus() })
  }

  // En la puerta y en la tarjeta solo se puede escribir la clave: el foco es SIEMPRE de su
  // campo. Se repone al caducar la puerta (ocultar el listado suelta el foco), al volver a la
  // ventana y si cualquier otra cosa lo toma.
  function ensureKeyFocus() {
    if (!visible) return
    if (carded) { if (!cardField.activeFocus) cardField.forceActiveFocus() }
    else if (gated && !gateView.fieldFocused) gateView.focusField()
  }
  Item {
    id: focusGuard
    readonly property var current: Window.activeFocusItem
    readonly property bool winActive: Window.active
    onCurrentChanged: Qt.callLater(win.ensureKeyFocus)
    onWinActiveChanged: Qt.callLater(win.ensureKeyFocus)
  }

  // ---- tarjeta del modo visible (ESQUEMA M6.T1.S2)
  FocusScope {
    id: cardView
    anchors.fill: parent
    visible: win.carded
    readonly property string err: win.service && win.service.rowErrors[win.service.cardId] ? win.service.rowErrors[win.service.cardId] : ""
    Column {
      anchors.centerIn: parent
      width: Math.min(parent.width - Style.space(40), Style.space(420))
      spacing: Style.space(12)
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: "󰉐"
        color: win.accent
        font.family: win.fontFamily
        font.pixelSize: Style.font.title * 3
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        text: win.service ? win.service.cardName : ""
        color: win.fg
        font.family: win.fontFamily
        font.pixelSize: Style.font.title
        font.weight: Font.DemiBold
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: win.t("card.hint")
        color: win.mutedFg
        font.family: win.fontFamily
        font.pixelSize: Style.font.body
      }
      PasswordField {
        id: cardField
        width: parent.width
        focus: true
        property bool useRecovery: false
        placeholder: win.service && win.service.busyId !== "" ? win.t("unlock.busy")
          : useRecovery ? win.t("unlock.recoveryPlaceholder") : win.t("unlock.placeholder")
        busy: !!win.service && win.service.busyId !== ""
        onSubmitted: function(password) { win.service.unlock(win.service.cardId, password, useRecovery) }
        onEscaped: win.visible = false
      }
      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        visible: !!win.service && win.service.cardType === "encrypt"
        text: cardField.useRecovery ? win.t("unlock.useNormal") : win.t("unlock.useRecovery")
        color: win.accent
        font.family: win.fontFamily
        font.pixelSize: Style.font.caption
        font.underline: true
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: { cardField.useRecovery = !cardField.useRecovery; cardField.clear(); cardField.forceActiveFocus() }
        }
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        visible: cardView.err !== ""
        textFormat: Text.PlainText
        text: cardView.err !== "" ? win.t("error." + cardView.err) : ""
        color: win.errorColor
        font.family: win.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  onGatedChanged: {
    if (visible) recenterTimer.restart()
    if (!gated && visible) Qt.callLater(function() { keys.forceActiveFocus() })
    if (gated && visible) Qt.callLater(win.ensureKeyFocus)
  }

  // Cualquier movimiento o clic dentro cuenta como «usar la ventana» (la puerta no caduca).
  HoverHandler { onPointChanged: if (win.service) win.service.touch() }
  TapHandler { onTapped: if (win.service) win.service.touch() }

  Timer { id: recenterTimer; interval: 120; onTriggered: if (win.service) win.service.fitWindow(win.implicitWidth, win.implicitHeight) }

  GateView {
    id: gateView
    anchors.fill: parent
    visible: win.gated
    win: win
    service: win.service
  }

  Item {
    id: keys
    anchors.fill: parent
    focus: true
    visible: !win.gated && !win.carded

    Keys.onPressed: function(event) {
      if (win.service) win.service.touch()
      var f = win.current()
      if (event.key === Qt.Key_Escape) {
        if (win.expandedId !== "") win.collapse()
        else win.visible = false
      } else if (event.key === Qt.Key_Down) {
        win.cursor = Math.min(win.folders.length - 1, win.cursor + 1)
      } else if (event.key === Qt.Key_Up) {
        win.cursor = Math.max(0, win.cursor - 1)
      } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
        win.activate(f)
      } else if (event.text === "L") {
        win.service.lockAll()
      } else if (event.text === "l" && f && win.isOpen(f.id)) {
        var row = list.itemAtIndex(win.cursor)
        if (row) row.requestLock(); else win.service.lock(f.id)
      } else if (event.text === "c" && f) {
        win.expand(f.id, "passwd")
      } else if (event.text === "e" && f) {
        win.openEdit(f)
      } else if (event.text === "n") {
        win.openCreate()
      } else if (event.text === ",") {
        win.openSettings()
      } else return
      event.accepted = true
    }

    Column {
      anchors.fill: parent
      anchors.margins: win.margin
      spacing: Style.space(12)

      // ---- cabecera: título a la izquierda, acciones a la derecha, en la misma línea
      Item {
        width: parent.width
        height: Math.max(titleRow.implicitHeight, headActions.implicitHeight)
        visible: win.page === "list"
        Row {
          id: titleRow
          spacing: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          Text {
            textFormat: Text.PlainText
            text: "󰌾"
            color: win.accent
            font.family: win.fontFamily
            font.pixelSize: Style.font.title + 4
            anchors.verticalCenter: parent.verticalCenter
          }
          Column {
            anchors.verticalCenter: parent.verticalCenter
            Text {
              textFormat: Text.PlainText
              text: win.t("plugin.name")
              color: win.fg
              font.family: win.fontFamily
              font.pixelSize: Style.font.title
              font.weight: Font.DemiBold
            }
            Text {
              textFormat: Text.PlainText
              text: win.t("window.summary").arg(win.folders.length).arg(win.service ? win.service.openIds.length : 0)
              color: win.mutedFg
              font.family: win.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              visible: !!win.service && win.service.devNoGate
              textFormat: Text.PlainText
              text: win.t("window.devNoGate")
              color: win.errorColor
              font.family: win.fontFamily
              font.pixelSize: Style.font.caption
              font.weight: Font.DemiBold
            }
          }
        }
        Row {
          id: headActions
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)
          Button { id: newButton; text: "+ " + win.t("action.new"); bordered: true; fontFamily: win.fontFamily; onClicked: win.openCreate() }
          // El glifo de la tuerca es más alto que el texto: se iguala a la altura del otro botón.
          Button { height: newButton.height; text: "󰒓"; tooltipText: win.t("settings.title"); bordered: true; fontFamily: win.fontFamily; onClicked: win.openSettings() }
        }
      }

      Rectangle { visible: win.page === "list"; width: parent.width; height: Style.normalBorderWidth; color: win.lineColor }

      Text {
        visible: win.page === "list" && !!win.service && win.service.globalError !== ""
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: win.service ? win.t("error." + win.service.globalError) : ""
        color: win.errorColor
        font.family: win.fontFamily
        font.pixelSize: Style.font.caption
      }

      // ---- listado
      ListView {
        id: list
        visible: win.page === "list"
        width: parent.width
        // deja sitio a la franja «sin registrar» (si se ve) y al pie de teclas
        height: parent.height - y - Style.space(30) - (orphanStrip.visible ? orphanStrip.height + parent.spacing : 0)
        clip: true
        spacing: Style.space(6)
        model: win.folders
        currentIndex: win.cursor

        // En un delegado, `win: win` se apuntaría a sí mismo (trampa de SWL): va por la lista.
        property var owner: win
        delegate: FolderRow { win: list.owner }

        Text {
          anchors.centerIn: parent
          visible: win.folders.length === 0 && !!win.service && win.service.globalError === ""
          textFormat: Text.PlainText
          text: win.t("window.empty")
          color: win.mutedFg
          font.family: win.fontFamily
          font.pixelSize: Style.font.body
        }
      }

      // ---- bóvedas sin registrar (registro borrado o perdido)
      Rectangle {
        id: orphanStrip
        visible: win.page === "list" && !!win.service && win.service.orphanIds.length > 0
        width: parent.width
        height: orphanRow.implicitHeight + Style.space(12)
        radius: Style.cornerRadius
        color: win.chipBg
        Item {
          id: orphanRow
          anchors.verticalCenter: parent.verticalCenter
          x: Style.space(10)
          width: parent.width - Style.space(20)
          implicitHeight: Math.max(orphanText.implicitHeight, orphanButton.implicitHeight)
          height: implicitHeight
          Column {
            id: orphanText
            anchors.left: parent.left
            anchors.right: orphanButton.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            Text {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              text: win.orphanTitle()
              color: win.fg
              font.family: win.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              text: win.t("orphans.hint")
              color: win.mutedFg
              font.family: win.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
          Button {
            id: orphanButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: win.t("orphans.readd")
            bordered: true
            fontFamily: win.fontFamily
            onClicked: win.openReadd(win.service.orphanIds[0])
          }
        }
      }

      // ---- sin gocryptfs no se puede crear ni abrir
      Text {
        visible: win.page === "list" && !!win.service && !win.service.gocryptfsOk
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: win.t("error.gocryptfs.missing")
        color: win.errorColor
        font.family: win.fontFamily
        font.pixelSize: Style.font.body
      }

      // ---- ⚙ ajustes generales (mínimo de la A)
      FocusScope {
        id: settingsPage
        visible: win.page === "settings"
        width: parent.width
        height: visible ? parent.height - Style.space(30) : 0
        Keys.onPressed: function(event) {
          if (win.capturing) {
            if (event.key === Qt.Key_Escape) win.capturing = false
            else {
              var chord = win.chordFromEvent(event)
              if (chord) { win.capturing = false; win.setDefault("openShortcut", chord) }
            }
            event.accepted = true
            return
          }
          if (event.key === Qt.Key_Escape) { win.backToList(); event.accepted = true }
        }
        Column {
          anchors.fill: parent
          spacing: Style.space(12)
          Text {
            textFormat: Text.PlainText
            text: win.t("settings.title")
            color: win.fg
            font.family: win.fontFamily
            font.pixelSize: Style.font.title
            font.weight: Font.DemiBold
          }
          Repeater {
            model: [
              { key: "showBarIcon", label: "settings.showBarIcon", top: true },
              { key: "showOpenDot", label: "settings.showOpenDot", top: true },
              { key: "notifyAutoLock", label: "settings.notifyAutoLock", top: true },
              { key: "hideOnShare", label: "settings.hideOnShare", top: true },
              { key: "idleLock", label: "rule.idle", first: true },
              { key: "maxOpenLock", label: "rule.maxOpen" },
              { key: "workspaceLock", label: "rule.workspace" },
              { key: "screenLock", label: "rule.screen" },
              { key: "openInFileManager", label: "rule.openFm" }
            ]
            delegate: Column {
             required property var modelData
             spacing: Style.space(6)
             Text {
               visible: !!modelData.first
               topPadding: Style.space(4)
               textFormat: Text.PlainText
               text: win.t("settings.defaultsCaption")
               color: win.mutedFg
               font.family: win.fontFamily
               font.pixelSize: Style.font.caption
             }
             Row {
              readonly property var modelData: parent.modelData
              readonly property bool on: modelData.top ? win.settings[modelData.key] === true : win.settings.defaults[modelData.key] === "on"
              spacing: Style.space(6)
              Text {
                width: Style.space(340)
                elide: Text.ElideRight
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: win.t(modelData.label)
                color: win.fg
                font.family: win.fontFamily
                font.pixelSize: Style.font.body
              }
              Button {
                text: win.t("rule.off"); bordered: true; selected: !parent.on; fontFamily: win.fontFamily
                onClicked: win.setDefault(modelData.key, modelData.top ? false : "off")
              }
              Button {
                text: win.t("rule.on"); bordered: true; selected: parent.on; fontFamily: win.fontFamily
                onClicked: win.setDefault(modelData.key, modelData.top ? true : "on")
              }
              Row {
                visible: (modelData.key === "idleLock" || modelData.key === "maxOpenLock") && parent.on
                spacing: Style.space(4)
                anchors.verticalCenter: parent.verticalCenter
                Button { text: "−"; bordered: true; fontFamily: win.fontFamily; onClicked: win.stepSetting(modelData.key, -1) }
                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(64)
                  horizontalAlignment: Text.AlignHCenter
                  textFormat: Text.PlainText
                  text: win.fmtSec(modelData.key === "idleLock" ? win.settings.defaults.idleSeconds : win.settings.defaults.maxOpenSeconds)
                  color: win.fg
                  font.family: win.fontFamily
                  font.pixelSize: Style.font.body
                }
                Button { text: "+"; bordered: true; fontFamily: win.fontFamily; onClicked: win.stepSetting(modelData.key, 1) }
              }
             }
            }
          }
          // volver a pedir la clave del sistema tras N sin usar la ventana
          Row {
            spacing: Style.space(4)
            Text {
              width: Style.space(340) + Style.space(2)
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: win.t("settings.gateTimeout")
              color: win.fg
              font.family: win.fontFamily
              font.pixelSize: Style.font.body
            }
            Button { text: "−"; bordered: true; fontFamily: win.fontFamily; onClicked: win.stepSetting("gateTimeoutSeconds", -1) }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(64)
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              text: win.fmtSec(win.settings.gateTimeoutSeconds)
              color: win.fg
              font.family: win.fontFamily
              font.pixelSize: Style.font.body
            }
            Button { text: "+"; bordered: true; fontFamily: win.fontFamily; onClicked: win.stepSetting("gateTimeoutSeconds", 1) }
          }
          // atajo: se captura pulsándolo
          Row {
            spacing: Style.space(6)
            Text {
              width: Style.space(340)
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: win.t("settings.shortcut")
              color: win.fg
              font.family: win.fontFamily
              font.pixelSize: Style.font.body
            }
            Button {
              text: win.capturing ? win.t("settings.pressKeys") : (win.settings.openShortcut || win.t("settings.noShortcut"))
              bordered: true
              selected: win.capturing
              fontFamily: win.fontFamily
              onClicked: { win.capturing = true; settingsPage.forceActiveFocus() }
            }
            Button {
              visible: win.settings.openShortcut !== "" && !win.capturing
              text: win.t("settings.clearShortcut")
              bordered: true
              fontFamily: win.fontFamily
              onClicked: win.setDefault("openShortcut", "")
            }
            Text {
              visible: !!win.service && win.service.shortcutConflict !== ""
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: win.t("settings.shortcutConflict")
              color: win.errorColor
              font.family: win.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
          Row {
            spacing: Style.space(8)
            visible: !!win.service && !win.service.gocryptfsOk
            Button { text: win.t("settings.install"); bordered: true; fontFamily: win.fontFamily; onClicked: win.service.installGocryptfs() }
          }
          Text {
            width: parent.width
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: win.t("settings.hint")
            color: win.mutedFg
            font.family: win.fontFamily
            font.pixelSize: Style.font.caption
          }
          Text {
            textFormat: Text.PlainText
            text: win.service && win.service.gocryptfsOk ? win.t("settings.gocryptfsOk") : win.t("error.gocryptfs.missing")
            color: win.service && win.service.gocryptfsOk ? win.mutedFg : win.errorColor
            font.family: win.fontFamily
            font.pixelSize: Style.font.caption
          }
          Button { text: win.t("form.back"); bordered: true; fontFamily: win.fontFamily; onClicked: win.backToList() }
        }
      }

      // ---- crear
      FolderForm {
        id: form
        visible: win.page === "create" || win.page === "edit" || win.page === "readd"
        win: win
        service: win.service
        width: parent.width
        height: parent.height - Style.space(30)
      }

      // ---- clave de recuperación: se enseña UNA vez y no se guarda
      FocusScope {
        id: recoveryPage
        visible: win.page === "recovery"
        width: parent.width
        height: visible ? parent.height - Style.space(30) : 0
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Escape) win.backToList()
          else if (event.text === "c") { win.service.copySecret(win.recoveryKey); win.copied = true }
          event.accepted = true
        }
        Column {
          anchors.fill: parent
          spacing: Style.space(14)
          Text {
            textFormat: Text.PlainText
            text: win.t("recovery.title").arg(win.recoveryName)
            color: win.fg
            font.family: win.fontFamily
            font.pixelSize: Style.font.title
            font.weight: Font.DemiBold
          }
          Text {
            width: parent.width
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: win.t("recovery.hint")
            color: win.mutedFg
            font.family: win.fontFamily
            font.pixelSize: Style.font.body
          }
          Rectangle {
            width: parent.width
            height: keyText.implicitHeight + Style.space(24)
            radius: Style.cornerRadius
            color: win.chipBg
            border.width: 1
            border.color: win.lineColor
            Text {
              id: keyText
              anchors.centerIn: parent
              textFormat: Text.PlainText
              text: win.recoveryKey
              color: win.accent
              font.family: win.fontFamily
              font.pixelSize: Style.font.title
            }
          }
          Row {
            spacing: Style.space(10)
            Button { text: win.copied ? win.t("recovery.copied") : win.t("recovery.copy"); bordered: true; fontFamily: win.fontFamily; onClicked: { win.service.copySecret(win.recoveryKey); win.copied = true } }
            Button { text: win.t("recovery.done"); bordered: true; selected: true; fontFamily: win.fontFamily; onClicked: win.backToList() }
          }
        }
      }

      // ---- pie: teclas
      Text {
        textFormat: Text.PlainText
        text: win.t(win.page === "list" ? "window.keys" : win.page === "create" ? "form.keys" : win.page === "edit" ? "form.editKeys" : win.page === "readd" ? "form.keys" : win.page === "settings" ? "settings.keys" : "recovery.keys")
        color: win.mutedFg
        font.family: win.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
