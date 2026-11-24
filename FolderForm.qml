import QtQuick
import QtQuick.Dialogs
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Formulario de una carpeta (ESQUEMA M4.T5 crear · M4.T6 editar). Ningún TextInput:
// textos con PlainEdit, claves con PasswordField, minutos con −/+. No guarda nada: al
// confirmar entrega los datos a `win.submitCreate`.
Item {
  id: form

  property var win: null
  property var service: null

  // ---- valores del formulario
  // Crear / volver a agregar: UNA ruta completa (elegida o escrita). Su estado se mira al
  // momento, antes de escribir las claves: "" · "checking" · "new" · "empty" · "error:<clave>"
  property string pathState: ""
  readonly property bool pathBad: pathProblem !== "" || (readding && pathState === "full")
  property string mode: "hidden"
  // Tipo: "hide" (esconder, sin copiar; por defecto) o "encrypt" (cifrar; solo nueva o vacía).
  property string kind: "hide"
  property bool canHide: true
  readonly property string pathProblem: pathState.indexOf("error:") === 0 ? errText(pathState.slice(6))
    : kind === "encrypt" && pathState === "full" ? t("form.encryptFull")
    : kind === "hide" && !canHide && pathState !== "" && pathState !== "checking" ? t("error.hide.otherDisk") : ""
  property var rules: ({ idleLock: "inherit", idleSeconds: null, workspaceLock: "inherit", screenLock: "inherit", openInFileManager: "inherit", maxOpenLock: "inherit", maxOpenSeconds: null })
  property string error: ""
  property bool busy: false
  // Editar (M4.T6): solo nombre y reglas; la ruta y la clave no se tocan aquí.
  property bool editing: false
  property string editId: ""
  // Volver a agregar una bóveda sin registrar (B6): ruta, nombre, modo, reglas y UNA clave.
  property bool readding: false

  readonly property var idleSteps: [60, 120, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200]
  readonly property var maxSteps: [300, 600, 900, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 28800, 43200, 86400]
  function stepMax(dir) {
    var cur = rules.maxOpenSeconds || 3600
    var i = maxSteps.indexOf(cur)
    if (i === -1) i = 5
    setRule("maxOpenSeconds", maxSteps[Math.max(0, Math.min(maxSteps.length - 1, i + dir))])
  }
  function fmtMin(sec) { return sec >= 3600 && sec % 3600 === 0 ? t("form.hours").arg(sec / 3600) : t("form.minutes").arg(Math.round(sec / 60)) }

  function t(k) { return win ? win.t(k) : k }

  function loadEdit(f) {
    reset()
    editing = true
    editId = f.id
    nameField.text = f.name || ""
    mode = f.mode === "visible" ? "visible" : "hidden"
    nameField.cursorPosition = nameField.text.length
    rules = ({ idleLock: f.idleLock || "inherit", idleSeconds: f.idleSeconds || null, workspaceLock: f.workspaceLock || "inherit",
               screenLock: f.screenLock || "inherit", openInFileManager: f.openInFileManager || "inherit",
               maxOpenLock: f.maxOpenLock || "inherit", maxOpenSeconds: f.maxOpenSeconds || null })
    Qt.callLater(function() { nameField.forceActiveFocus() })
  }

  function loadReadd() {
    reset()
    readding = true
  }

  function reset() {
    editing = false
    readding = false
    editId = ""
    nameField.text = ""
    nameField.cursorPosition = 0
    key1.clear()
    key2.clear()
    mode = "hidden"
    kind = "hide"
    canHide = true
    rules = ({ idleLock: "inherit", idleSeconds: null, workspaceLock: "inherit", screenLock: "inherit", openInFileManager: "inherit", maxOpenLock: "inherit", maxOpenSeconds: null })
    error = ""
    busy = false
    pathField.text = "~/"
    pathField.cursorPosition = 2
    pathState = ""
    Qt.callLater(function() { pathField.forceActiveFocus() })
  }

  function expand(p) {
    var home = Quickshell.env("HOME")
    p = String(p || "").trim()
    if (p === "~") return home
    if (p.indexOf("~/") === 0) return home + p.slice(1)
    return p
  }

  function targetPath() { return expand(pathField.text).replace(/\/+$/, "") }
  function atHome() { var p = targetPath(); return p === "" || p === Quickshell.env("HOME") }
  function diskNote() { return targetPath().indexOf(Quickshell.env("HOME") + "/") === 0 ? "" : " · " + t(kind === "hide" ? "form.onDiskHide" : "form.onDisk") }
  function errText(key) { return t(key === "path.notEmpty" ? "form.notEmpty" : "error." + key) }
  function used() { if (service) service.touch() }   // escribir también es usar la ventana

  function pathEdited() {
    used()
    error = ""
    pathState = atHome() ? "" : "checking"
    if (!editing && visible && pathState !== "") checkTimer.restart()
    else checkTimer.stop()
  }
  Timer {
    id: checkTimer
    interval: 300
    onTriggered: {
      var p = form.targetPath()
      form.service.checkPath(p, function(r) {
        if (p !== form.targetPath()) return            // ya se escribió otra cosa
        form.canHide = !r.ok || r.data.canHide !== false
        form.pathState = r.ok ? r.data.state : "error:" + r.error
      })
    }
  }

  function setRule(key, value) {
    var next = Object.assign({}, rules)
    next[key] = value
    rules = next
  }

  function stepIdle(dir) {
    var cur = rules.idleSeconds || 600
    var i = idleSteps.indexOf(cur)
    if (i === -1) i = 3
    setRule("idleSeconds", idleSteps[Math.max(0, Math.min(idleSteps.length - 1, i + dir))])
  }

  function submit() {
    if (busy) return
    var name = nameField.text.trim()
    if (editing) {
      if (name.length === 0 || name.length > 60) { error = "form.nameInvalid"; return }
      error = ""
      busy = true
      win.submitEdit(editId, { name: name, rules: rules, mode: mode }, function(r) {
        form.busy = false
        if (!r.ok) form.error = "error." + r.error
      })
      return
    }
    if (atHome()) { error = "form.pathEmpty"; return }
    if (pathBad) return                                 // el motivo ya se ve bajo la ruta
    if (readding) {
      if (key1.value.length === 0) { error = "error.key.empty"; return }
      error = ""
      busy = true
      var k = key1.value
      key1.clear()
      win.submitReadd({ path: targetPath(), rules: rules, mode: mode }, k, function(r) {
        form.busy = false
        if (!r.ok) form.error = "error." + r.error
      })
      return
    }
    if (key1.value.length < 5) { error = "error.key.short"; return }
    if (key1.value !== key2.value) { error = "form.keysDiffer"; return }
    error = ""
    busy = true
    var key = key1.value
    key1.clear()
    key2.clear()
    win.submitCreate({ path: targetPath(), type: kind, rules: rules, mode: mode }, key, function(r) {
      form.busy = false
      if (!r.ok) form.error = "error." + r.error
    })
  }

  FolderDialog {
    id: picker
    title: form.t("form.pickTitle")
    currentFolder: "file://" + (form.targetPath() || Quickshell.env("HOME"))
    onAccepted: {
      var p = decodeURIComponent(String(selectedFolder).replace(/^file:\/\//, ""))
      var home = Quickshell.env("HOME")
      pathField.text = p === home || p.indexOf(home + "/") === 0 ? "~" + p.slice(home.length) : p
      pathField.cursorPosition = pathField.text.length
      Qt.callLater(function() { pathField.forceActiveFocus() })
    }
  }

  // ---- piezas
  component Label: Text {
    width: Style.space(170)
    textFormat: Text.PlainText
    color: form.win.fg
    font.family: form.win.fontFamily
    font.pixelSize: Style.font.body
    anchors.verticalCenter: parent ? parent.verticalCenter : undefined
  }

  component FieldBox: Rectangle {
    default property alias content: inner.data
    width: Style.space(380)
    height: Style.space(34)
    radius: Style.cornerRadius
    color: Qt.rgba(1, 1, 1, 0.06)
    border.width: 1
    border.color: Qt.rgba(1, 1, 1, 0.22)
    Item { id: inner; anchors.fill: parent; anchors.leftMargin: Style.space(10); anchors.rightMargin: Style.space(10) }
  }

  // inherit / off / on de una regla
  component RuleRow: Row {
    id: rr
    property string ruleKey: ""
    property string label: ""
    spacing: Style.space(6)
    Label { text: rr.label; width: Style.space(270) }
    Repeater {
      model: ["inherit", "off", "on"]
      Button {
        required property string modelData
        text: form.t("rule." + modelData)
        bordered: true
        selected: form.rules[rr.ruleKey] === modelData
        fontFamily: form.win.fontFamily
        onClicked: form.setRule(rr.ruleKey, modelData)
      }
    }
  }

  Column {
    anchors.fill: parent
    spacing: Style.space(10)

    Text {
      textFormat: Text.PlainText
      text: form.editing ? form.t("form.editTitle") : form.readding ? form.t("form.readdTitle") : form.t("form.createTitle")
      color: form.win.fg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.title
      font.weight: Font.DemiBold
    }
    Text {
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: form.editing ? form.t("form.editHint") : form.readding ? form.t("form.readdHint")
        : form.t(form.kind === "encrypt" ? "form.createHintEncrypt" : "form.createHint")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      visible: !form.editing
      spacing: Style.space(8)
      Label { text: form.t("form.folder") }
      FieldBox {
        border.color: form.pathBad ? form.win.errorColor : Qt.rgba(1, 1, 1, 0.22)
        PlainEdit {
          id: pathField
          anchors.fill: parent
          text: "~/"
          color: form.win.fg
          fontFamily: form.win.fontFamily
          fontPixelSize: Style.font.body
          nextField: key1
          onTextChanged: form.pathEdited()
          onPreKey: function(event) {
            if (event.key === Qt.Key_Escape) { form.win.backToList(); event.accepted = true }
          }
        }
      }
      Button { text: form.t("form.pick"); bordered: true; fontFamily: form.win.fontFamily; onClicked: picker.open() }
    }
    Text {
      visible: !form.editing
      leftPadding: Style.space(178)
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: form.pathProblem !== "" ? form.pathProblem
        : form.pathBad ? form.t("form.notEmpty")
        : form.pathState === "full" ? form.t("form.stateFull") + form.diskNote()
        : form.pathState === "new" ? form.t("form.stateNew") + form.diskNote()
        : form.pathState === "empty" ? form.t("form.stateEmpty") + form.diskNote()
        : form.pathState === "checking" ? "…" : form.t("form.pathHint")
      color: form.pathBad ? form.win.errorColor : form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    // el nombre del listado: solo al editar (al crear es el de la carpeta)
    Row {
      visible: form.editing
      spacing: Style.space(8)
      Label { text: form.t("form.name") }
      FieldBox {
        PlainEdit {
          id: nameField
          anchors.fill: parent
          color: form.win.fg
          fontFamily: form.win.fontFamily
          fontPixelSize: Style.font.body
          onTextChanged: form.used()
          onPreKey: function(event) {
            if (event.key === Qt.Key_Escape) { form.win.backToList(); event.accepted = true }
            else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { form.submit(); event.accepted = true }
          }
        }
      }
    }

    // tipo de bloqueo: solo al crear (después no se cambia: convertir sería copiar)
    Row {
      visible: !form.editing && !form.readding
      spacing: Style.space(6)
      Label { text: form.t("form.kind") }
      Button { text: "󰈉  " + form.t("kind.hide"); bordered: true; selected: form.kind === "hide"; fontFamily: form.win.fontFamily; onClicked: { form.kind = "hide"; form.used() } }
      Button { text: "󰌾  " + form.t("kind.encrypt"); bordered: true; selected: form.kind === "encrypt"; fontFamily: form.win.fontFamily; onClicked: { form.kind = "encrypt"; form.used() } }
    }
    Text {
      visible: !form.editing && !form.readding
      leftPadding: Style.space(178)
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: form.t(form.kind === "hide" ? "kind.hideHint" : "kind.encryptHint")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      spacing: Style.space(6)
      Label { text: form.t("form.mode") }
      Button { text: form.t("mode.hiddenShort"); bordered: true; selected: form.mode === "hidden"; fontFamily: form.win.fontFamily; onClicked: form.mode = "hidden" }
      Button { text: form.t("mode.visibleShort"); bordered: true; selected: form.mode === "visible"; fontFamily: form.win.fontFamily; onClicked: form.mode = "visible" }
    }
    Text {
      leftPadding: Style.space(178)
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: form.t(form.mode === "visible" ? "mode.visibleHint" : "mode.hiddenHint")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      visible: !form.editing
      spacing: Style.space(8)
      Label { text: form.t("form.key") }
      PasswordField {
        id: key1
        onValueChanged: form.used()
        width: Style.space(380)
        height: Style.space(34)
        placeholder: form.t("form.keyPlaceholder")
        nextField: key2
        prevField: pathField
        onSubmitted: function(pw) { key1.value = pw; if (form.readding) form.submit(); else key2.forceActiveFocus() }
        onEscaped: form.win.backToList()
      }
    }
    Row {
      visible: !form.editing && !form.readding
      spacing: Style.space(8)
      Label { text: form.t("form.key2") }
      PasswordField {
        id: key2
        onValueChanged: form.used()
        width: Style.space(380)
        height: Style.space(34)
        placeholder: form.t("form.key2Placeholder")
        prevField: key1
        onSubmitted: function(pw) { key2.value = pw; form.submit() }
        onEscaped: form.win.backToList()
      }
    }

    Rectangle { width: parent.width; height: Style.normalBorderWidth; color: form.win.lineColor }
    Text {
      textFormat: Text.PlainText
      text: form.t("form.autoLock")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      spacing: Style.space(12)
      RuleRow { ruleKey: "idleLock"; label: form.t("rule.idle") }
      Row {
        spacing: Style.space(4)
        visible: form.rules.idleLock === "on"
        anchors.verticalCenter: parent.verticalCenter
        Button { text: "−"; bordered: true; fontFamily: form.win.fontFamily; onClicked: form.stepIdle(-1) }
        Text {
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(64)
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: form.t("form.minutes").arg(Math.round((form.rules.idleSeconds || 600) / 60))
          color: form.win.fg
          font.family: form.win.fontFamily
          font.pixelSize: Style.font.body
        }
        Button { text: "+"; bordered: true; fontFamily: form.win.fontFamily; onClicked: form.stepIdle(1) }
      }
    }
    Row {
      spacing: Style.space(12)
      RuleRow { ruleKey: "maxOpenLock"; label: form.t("rule.maxOpen") }
      Row {
        spacing: Style.space(4)
        visible: form.rules.maxOpenLock === "on"
        anchors.verticalCenter: parent.verticalCenter
        Button { text: "−"; bordered: true; fontFamily: form.win.fontFamily; onClicked: form.stepMax(-1) }
        Text {
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(64)
          horizontalAlignment: Text.AlignHCenter
          textFormat: Text.PlainText
          text: form.fmtMin(form.rules.maxOpenSeconds || 3600)
          color: form.win.fg
          font.family: form.win.fontFamily
          font.pixelSize: Style.font.body
        }
        Button { text: "+"; bordered: true; fontFamily: form.win.fontFamily; onClicked: form.stepMax(1) }
      }
    }
    RuleRow { ruleKey: "workspaceLock"; label: form.t("rule.workspace") }
    RuleRow { ruleKey: "screenLock"; label: form.t("rule.screen") }

    // No tiene que ver con bloquear: va en su propio grupo.
    Rectangle { width: parent.width; height: Style.normalBorderWidth; color: form.win.lineColor }
    Text {
      textFormat: Text.PlainText
      text: form.t("form.whenOpening")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }
    RuleRow { ruleKey: "openInFileManager"; label: form.t("rule.openFm") }

    Text {
      width: parent.width
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      visible: !form.editing && !form.readding
      text: form.t(form.kind === "hide" ? "form.warningHide" : "form.warning")
      color: form.win.mutedFg
      font.family: form.win.fontFamily
      font.pixelSize: Style.font.caption
    }

    Row {
      spacing: Style.space(10)
      Button { text: form.t("form.cancel"); bordered: true; fontFamily: form.win.fontFamily; onClicked: form.win.backToList() }
      Button { text: form.busy ? form.t("form.saving") : form.editing ? form.t("form.save") : form.readding ? form.t("orphans.readd") : form.t("form.create"); bordered: true; selected: true; fontFamily: form.win.fontFamily; onClicked: form.submit() }
      Text {
        visible: form.error !== ""
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: form.error === "" ? "" : form.t(form.error === "error.path.notEmpty" ? "form.notEmpty" : form.error)
        color: form.win.errorColor
        font.family: form.win.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
