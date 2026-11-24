import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Icono en la barra (ESQUEMA M5): un candado NEUTRO que abre la ventana. No cambia de
// forma, no cuenta carpetas ni dice si hay alguna abierta (no delata), y no tiene menú:
// el listado solo existe dentro de la ventana, tras la puerta. Con `showBarIcon: false`
// no pinta nada; el servicio sigue corriendo igual (se entra por el lanzador o la IPC).
BarWidget {
  id: root
  moduleName: "leninzapata.super-folder-lock"

  readonly property var service: bar && bar.shell ? bar.shell.firstPartyServiceFor("leninzapata.super-folder-lock") : null
  readonly property bool shown: !service || !service.settings || service.settings.showBarIcon !== false

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  visible: shown
  implicitWidth: shown ? button.implicitWidth : 0
  implicitHeight: shown ? button.implicitHeight : 0

  BarIconButton {
    id: button
    anchors.fill: parent
    visible: root.shown
    bar: root.bar
    text: "󰉐"
    tooltipText: strings.t("plugin.name")
    onPressed: function(buttonCode) { if (root.service) root.service.open() }
  }

  // Punto discreto con alguna carpeta abierta: solo si Lenin lo activa (delata; B7).
  Rectangle {
    visible: root.shown && !!root.service && root.service.settings.showOpenDot && root.service.openIds.length > 0
    width: 5
    height: 5
    radius: 2.5
    color: Color.accent
    anchors.right: button.right
    anchors.top: button.top
    anchors.rightMargin: 3
    anchors.topMargin: 4
  }
}
