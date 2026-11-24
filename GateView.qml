import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Puerta de la ventana (ESQUEMA M3): hasta pasar la clave del sistema no se carga
// nada del registro. Al pasarla, `service.gateOpen = true` y se pide la lista.
FocusScope {
  id: gate

  property var win: null
  property var service: null
  property string errorKey: ""
  property int triesLeft: 0
  property int waitSeconds: 0

  function t(k) { return win ? win.t(k) : k }
  readonly property bool fieldFocused: field.activeFocus
  function focusField() { field.forceActiveFocus() }
  function reset() { errorKey = ""; field.clear() }

  Auth {
    id: auth
    onSucceeded: {
      gate.errorKey = ""
      gate.service.openGate()
    }
    onFailed: function(left, wait) {
      gate.triesLeft = left
      gate.waitSeconds = wait
      gate.errorKey = wait > 0 ? "gate.locked" : "gate.wrong"
      if (wait > 0) waitTimer.restart()
      field.clear()
      field.forceActiveFocus()
    }
  }

  Timer {
    id: waitTimer
    interval: 1000
    repeat: true
    onTriggered: {
      gate.waitSeconds = Math.max(0, gate.waitSeconds - 1)
      if (gate.waitSeconds === 0) { stop(); gate.errorKey = "" }
    }
  }

  Column {
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(40), Style.space(420))
    spacing: Style.space(12)

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: "󰌾"
      color: gate.win.accent
      font.family: gate.win.fontFamily
      font.pixelSize: Style.font.title * 3
    }
    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      text: gate.t("plugin.name")
      color: gate.win.fg
      font.family: gate.win.fontFamily
      font.pixelSize: Style.font.title
      font.weight: Font.DemiBold
    }
    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      text: gate.t("gate.hint")
      color: gate.win.mutedFg
      font.family: gate.win.fontFamily
      font.pixelSize: Style.font.body
    }
    PasswordField {
      id: field
      width: parent.width
      focus: true
      placeholder: auth.busy ? gate.t("gate.busy") : gate.t("gate.placeholder")
      busy: auth.busy || gate.waitSeconds > 0
      onSubmitted: function(password) { auth.submit(password) }
      onEscaped: gate.win.dismiss()
    }
    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      visible: gate.errorKey !== ""
      textFormat: Text.PlainText
      text: gate.errorKey === "gate.locked" ? gate.t("gate.locked").arg(gate.waitSeconds)
        : gate.errorKey === "gate.wrong" ? gate.t("gate.wrong").arg(gate.triesLeft) : ""
      color: gate.win.errorColor
      font.family: gate.win.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}
