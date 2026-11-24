import QtQuick
import qs.Commons as Commons

// Campo de clave dibujado por el plugin, SIN TextInput: un campo nativo editable
// lee el portapapeles ajeno (reparo del marketplace a super-clipboard). Aquí no
// hay pegar, ni seleccionar, ni deshacer: solo escribir, borrar y enviar.
Rectangle {
  id: root

  property string placeholder: ""
  property bool busy: false
  // La clave vive solo aquí hasta Enter; al enviarla se vacía.
  property string value: ""
  // Tab / Shift+Tab: siguiente / anterior campo del formulario (añadido en Super Folder Lock).
  property Item nextField: null
  property Item prevField: null

  signal submitted(string password)
  // Esc con el campo ya vacío: quien lo contiene recupera el foco (ajustes).
  signal escaped()

  implicitWidth: 320
  implicitHeight: 44
  radius: Commons.Style.cornerRadius
  color: Qt.rgba(1, 1, 1, 0.08)
  border.width: activeFocus ? 2 : 1
  border.color: activeFocus ? Commons.Color.accent : Qt.rgba(1, 1, 1, 0.25)

  // Color del texto de ayuda: `muted` del tema o el del texto al 38 %, el que MEJOR se lea sobre el
  // campo. Solo `muted` no vale (en Hackerman casi no se ve) y solo el 38 % tampoco (Ethereal).
  readonly property color hintColor: pickHint(Commons.Color.background, Commons.Color.foreground, Commons.Color.muted)
  function blend(over, under, t) { return Qt.rgba(over.r * t + under.r * (1 - t), over.g * t + under.g * (1 - t), over.b * t + under.b * (1 - t), 1) }
  function luminance(c) {
    var f = function(x) { return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
  }
  function contrast(a, b) {
    var x = luminance(a), y = luminance(b)
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
  }
  function pickHint(bg, fg, muted) {
    var field = blend(Qt.rgba(1, 1, 1, 1), bg, 0.08), soft = blend(fg, field, 0.38)
    return contrast(soft, field) >= contrast(muted, field) ? soft : muted
  }

  function clear() { value = "" }

  // Clic = foco (en la ventana de ajustes hay dos campos).
  MouseArea { anchors.fill: parent; onClicked: root.forceActiveFocus() }

  Keys.onPressed: function(event) {
    if (busy) { event.accepted = true; return }
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      if (value.length > 0) {
        var pw = value
        value = ""
        root.submitted(pw)
      }
    } else if (event.key === Qt.Key_Tab && nextField) {
      nextField.forceActiveFocus()
    } else if (event.key === Qt.Key_Backtab && prevField) {
      prevField.forceActiveFocus()
    } else if (event.key === Qt.Key_Escape) {
      if (value.length === 0) root.escaped()
      value = ""
    } else if (event.key === Qt.Key_Backspace) {
      value = value.slice(0, -1)
    } else if (event.text.length > 0 && event.text.charCodeAt(0) >= 32
               && !(event.modifiers & (Qt.ControlModifier | Qt.MetaModifier))) {
      value += event.text
    }
    event.accepted = true
  }

  Text {
    anchors.fill: parent
    anchors.leftMargin: 14
    anchors.rightMargin: 14
    verticalAlignment: Text.AlignVCenter
    textFormat: Text.PlainText
    font.family: Commons.Style.font.menuFamily
    font.pixelSize: root.value.length > 0 ? 20 : 15
    color: root.value.length > 0 ? Commons.Color.foreground : root.hintColor
    elide: Text.ElideLeft
    text: root.value.length > 0 ? "•".repeat(root.value.length) : root.placeholder
  }
}
