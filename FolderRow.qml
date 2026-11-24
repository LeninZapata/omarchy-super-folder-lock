import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Una fila del listado (ESQUEMA M4.T2-T4): estado, nombre, modo, ruta y sus acciones.
// Se expande en línea (como Cryptomator, REF-3) para dos cosas: la clave de abrir
// (`win.expandMode === "unlock"`) y el cambio rápido de clave ("passwd"). No guarda
// nada: cada acción va al servicio; las claves solo viven en sus PasswordField.
Rectangle {
  id: row

  required property var modelData
  required property int index
  property var win: null

  readonly property var service: win ? win.service : null
  readonly property bool opened: !!win && win.isOpen(modelData.id)
  readonly property bool expanded: !!win && win.expandedId === modelData.id
  readonly property bool unlocking: expanded && win.expandMode === "unlock"
  readonly property bool changing: expanded && win.expandMode === "passwd"
  readonly property bool selected: !!win && index === win.cursor
  readonly property string error: service && service.rowErrors[modelData.id] ? service.rowErrors[modelData.id] : ""
  readonly property bool busy: !!service && service.busyId === modelData.id
  property string notice: ""
  // «Usar clave de recuperación»: el mismo campo, otra clave (B3).
  property bool useRecovery: false
  // B4: programas con archivos abiertos dentro, y confirmación antes de bloquear a mano.
  readonly property var apps: opened && service && service.holders[modelData.id] ? service.holders[modelData.id] : []
  readonly property int secondsLeft: opened && service ? service.closeIn(modelData.id) : -1
  property bool confirmLock: false
  // ⋯ → olvidar del listado · quitar protección (los archivos se quedan; pide la clave)
  property bool moreOpen: false
  property bool confirmUnprotect: false
  property bool confirmForget: false
  readonly property bool encrypted: modelData.type !== "hide"
  readonly property bool unprotecting: !!service && service.unprotectId === modelData.id
  function requestLock() {
    if (apps.length > 0 && !confirmLock) { confirmLock = true; return }
    confirmLock = false
    service.lock(modelData.id)
  }
  function mmss(s) { var m = Math.floor(s / 60), r = s % 60; return m + ":" + (r < 10 ? "0" : "") + r }

  width: ListView.view ? ListView.view.width : 0
  height: content.implicitHeight + Style.space(16)
  radius: Style.cornerRadius
  color: selected ? win.chipBg : "transparent"
  border.width: selected ? Style.normalBorderWidth : 0
  border.color: win.lineColor

  function focusFirst() {
    if (unlocking) Qt.callLater(function() { unlockField.forceActiveFocus() })
    else if (changing) Qt.callLater(function() { oldField.forceActiveFocus() })
  }
  onExpandedChanged: { notice = ""; useRecovery = false; confirmLock = false; moreOpen = false; confirmUnprotect = false; confirmForget = false; if (expanded) focusFirst() }
  onUnlockingChanged: if (unlocking) focusFirst()
  onChangingChanged: if (changing) focusFirst()

  function submitUnprotect(password) {
    service.unprotect(modelData.id, password, function(r) { if (r.ok && row) { row.confirmUnprotect = false; row.moreOpen = false } })
  }

  function submitPasswd() {
    if (oldField.value.length === 0) return
    if (newField.value.length < 5) { service.setRowError(modelData.id, "key.short"); return }
    if (newField.value !== new2Field.value) { service.setRowError(modelData.id, "form.keysDiffer"); return }
    var o = oldField.value, n = newField.value
    oldField.clear(); newField.clear(); new2Field.clear()
    service.changeKey(modelData.id, o, n, function(r) {
      if (r.ok) { row.win.collapse(); row.notice = row.win.t("passwd.done") }
    })
  }

  component ActionCard: Rectangle {
    id: card
    property string title: ""
    property string description: ""
    readonly property bool usable: !row.opened && !row.unprotecting
    signal activated()
    implicitHeight: cardText.implicitHeight + Style.space(20)
    radius: Style.cornerRadius
    color: cardMouse.containsMouse && usable ? Util.alpha(row.win.fg, 0.14) : Util.alpha(row.win.fg, 0.05)
    border.width: Math.max(1, Style.normalBorderWidth)
    border.color: cardMouse.containsMouse && usable ? row.win.accent : Util.alpha(row.win.fg, 0.28)
    opacity: usable ? 1 : 0.5
    Column {
      id: cardText
      x: Style.space(12)
      y: Style.space(10)
      width: card.width - Style.space(24)
      spacing: Style.space(4)
      Text {
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: card.title
        color: row.win.fg
        font.family: row.win.fontFamily
        font.pixelSize: Style.font.body
        font.weight: Font.DemiBold
      }
      Text {
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: row.opened ? row.win.t("more.lockFirst") : card.description
        color: row.win.mutedFg
        font.family: row.win.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
    MouseArea {
      id: cardMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: card.usable ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (card.usable) card.activated()
    }
  }

  MouseArea {
    anchors.fill: parent
    onClicked: row.win.cursor = row.index
    onDoubleClicked: { row.win.cursor = row.index; row.win.activate(row.modelData) }
  }

  Column {
    id: content
    x: Style.space(10)
    y: Style.space(8)
    width: parent.width - Style.space(20)
    spacing: Style.space(8)

    // ---- cabecera de la fila: estado · nombre · insignias · ruta | acciones
    Item {
      width: parent.width
      height: Math.max(info.implicitHeight, actions.implicitHeight)

      Row {
        id: info
        spacing: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - actions.width - Style.space(10)
        Text {
          textFormat: Text.PlainText
          text: row.opened ? "󰌿" : "󰌾"
          color: row.opened ? row.win.openColor : row.win.mutedFg
          font.family: row.win.fontFamily
          font.pixelSize: Style.font.title
          anchors.verticalCenter: parent.verticalCenter
        }
        Column {
          width: parent.width - Style.space(40)
          anchors.verticalCenter: parent.verticalCenter
          Row {
            spacing: Style.space(8)
            Text {
              id: nameText
              textFormat: Text.PlainText
              text: row.modelData.name
              color: row.win.fg
              font.family: row.win.fontFamily
              font.pixelSize: Style.font.body
              font.weight: Font.DemiBold
            }
            Text {
              anchors.baseline: nameText.baseline
              textFormat: Text.PlainText
              text: (row.opened ? row.win.t("state.open") : row.win.t("state.locked")) + " · "
                + row.win.t(row.modelData.mode === "visible" ? "mode.visible" : "mode.hidden")
                + (row.encrypted ? " · " + row.win.t("kind.badge") : "")
              color: row.opened ? row.win.openColor : row.win.mutedFg
              font.family: row.win.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
          Text {
            width: parent.width
            elide: Text.ElideMiddle
            textFormat: Text.PlainText
            text: row.win.shortPath(row.modelData.path)
            color: row.win.mutedFg
            font.family: row.win.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Row {
        id: actions
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)
        visible: !row.expanded
        Button {
          visible: !row.opened
          text: "󰌿 " + row.win.t("action.open")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: { row.win.cursor = row.index; row.win.activate(row.modelData) }
        }
        Button {
          visible: row.opened
          text: "󰉋 " + row.win.t("action.view")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: row.service.view(row.modelData.id)
        }
        Button {
          visible: row.opened && !!row.service && row.service.maxOpenOn(row.modelData.id)
          text: "󰔟 +15"
          tooltipText: row.win.t("action.postpone")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: row.service.postpone(row.modelData.id)
        }
        Button {
          visible: row.opened
          text: "󰌾 " + row.win.t("action.lock")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: row.requestLock()
        }
        Button {
          text: "󰌋"
          tooltipText: row.win.t("action.passwd")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: { row.win.cursor = row.index; row.win.expand(row.modelData.id, "passwd") }
        }
        Button {
          text: "󰇘"
          tooltipText: row.win.t("action.more")
          bordered: true
          selected: row.moreOpen
          fontFamily: row.win.fontFamily
          onClicked: { row.win.cursor = row.index; row.moreOpen = !row.moreOpen; row.confirmUnprotect = false; row.confirmForget = false }
        }
        Button {
          text: "󰏫"
          tooltipText: row.win.t("action.edit")
          bordered: true
          fontFamily: row.win.fontFamily
          onClicked: { row.win.cursor = row.index; row.win.openEdit(row.modelData) }
        }
      }
    }

    // ---- abierta: quién la usa y cuándo se cierra sola
    Text {
      visible: row.opened && (row.apps.length > 0 || row.secondsLeft >= 0)
      leftPadding: Style.space(30)
      textFormat: Text.PlainText
      text: (row.apps.length > 0 ? row.win.t("row.inUse").arg(row.apps.join(", ")) : "")
        + (row.apps.length > 0 && row.secondsLeft >= 0 ? "  ·  " : "")
        + (row.secondsLeft >= 0 ? row.win.t("row.closesIn").arg(row.mmss(row.secondsLeft)) : "")
      color: row.win.mutedFg
      font.family: row.win.fontFamily
      font.pixelSize: Style.font.caption
    }
    Row {
      visible: row.confirmLock
      spacing: Style.space(8)
      leftPadding: Style.space(30)
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: row.win.t("row.lockWarning").arg(row.apps.join(", "))
        color: row.win.errorColor
        font.family: row.win.fontFamily
        font.pixelSize: Style.font.caption
      }
      Button { text: row.win.t("row.lockAnyway"); bordered: true; fontFamily: row.win.fontFamily; onClicked: row.requestLock() }
      Button { text: row.win.t("form.cancel"); bordered: true; fontFamily: row.win.fontFamily; onClicked: row.confirmLock = false }
    }

    // ---- ⋯ más: dos botones anchos, cada uno explica dentro lo que hace
    Row {
      id: moreCards
      visible: row.moreOpen && !row.confirmUnprotect && !row.confirmForget
      width: parent.width
      spacing: Style.space(8)
      readonly property real cardWidth: (width - spacing) / 2
      readonly property real cardHeight: Math.max(forgetCard.implicitHeight, unprotectCard.implicitHeight)
      ActionCard {
        id: forgetCard
        width: moreCards.cardWidth
        height: moreCards.cardHeight
        title: "󰈉  " + row.win.t("more.forget")
        description: row.win.t(row.encrypted ? "more.forgetDesc" : "more.forgetDescHide")
        onActivated: row.confirmForget = true
      }
      ActionCard {
        id: unprotectCard
        width: moreCards.cardWidth
        height: moreCards.cardHeight
        title: "󰿆  " + row.win.t("more.unprotect")
        description: row.win.t(row.encrypted ? "more.unprotectDesc" : "more.unprotectDescHide")
        onActivated: { row.confirmUnprotect = true; Qt.callLater(function() { unprotectField.forceActiveFocus() }) }
      }
    }
    Column {
      visible: row.confirmForget
      width: parent.width
      spacing: Style.space(6)
      Text {
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: row.win.t(row.encrypted ? "forget.confirm" : "forget.confirmHide").arg(row.modelData.name)
        color: row.win.fg
        font.family: row.win.fontFamily
        font.pixelSize: Style.font.caption
      }
      Row {
        spacing: Style.space(8)
        Button {
          text: row.win.t("more.forget")
          bordered: true
          selected: true
          fontFamily: row.win.fontFamily
          onClicked: row.service.forgetFolder(row.modelData.id, function(r) { if (row) { row.confirmForget = false; row.moreOpen = false } })
        }
        Button { text: row.win.t("form.cancel"); bordered: true; fontFamily: row.win.fontFamily; onClicked: row.confirmForget = false }
      }
    }
    Column {
      visible: row.confirmUnprotect
      width: parent.width
      spacing: Style.space(6)
      leftPadding: Style.space(30)
      Text {
        width: parent.width - Style.space(30)
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        text: row.unprotecting ? row.win.t("unprotect.working")
          : row.win.t(row.encrypted ? "unprotect.explain" : "unprotect.explainHide").arg(row.win.shortPath(row.modelData.path))
        color: row.win.fg
        font.family: row.win.fontFamily
        font.pixelSize: Style.font.caption
      }
      Row {
        visible: !row.unprotecting
        spacing: Style.space(8)
        PasswordField {
          id: unprotectField
          width: Style.space(260)
          height: Style.space(34)
          placeholder: row.win.t("unlock.placeholder")
          onSubmitted: function(password) { row.submitUnprotect(password) }
          onEscaped: row.confirmUnprotect = false
          onValueChanged: if (row.service) row.service.touch()
        }
        Button {
          text: row.win.t("more.unprotect")
          bordered: true
          selected: true
          fontFamily: row.win.fontFamily
          anchors.verticalCenter: parent.verticalCenter
          onClicked: {
            if (unprotectField.value.length === 0) return
            var pw = unprotectField.value
            unprotectField.clear()
            row.submitUnprotect(pw)
          }
        }
        Button { text: row.win.t("form.cancel"); bordered: true; fontFamily: row.win.fontFamily; anchors.verticalCenter: parent.verticalCenter; onClicked: { unprotectField.clear(); row.confirmUnprotect = false } }
      }
    }

    // ---- abrir: la clave en línea
    Row {
      visible: row.unlocking
      spacing: Style.space(8)
      PasswordField {
        id: unlockField
        onValueChanged: if (row.service) row.service.touch()
        width: Style.space(340)
        placeholder: row.useRecovery ? row.win.t("unlock.recoveryPlaceholder") : row.win.t("unlock.placeholder")
        busy: row.busy
        onSubmitted: function(password) { row.service.unlock(row.modelData.id, password, row.useRecovery) }
        onEscaped: row.win.collapse()
      }
      Button {
        text: row.busy ? row.win.t("unlock.busy") : row.win.t("action.open")
        bordered: true
        fontFamily: row.win.fontFamily
        anchors.verticalCenter: parent.verticalCenter
        onClicked: {
          if (unlockField.value.length === 0) return
          var pw = unlockField.value
          unlockField.clear()
          row.service.unlock(row.modelData.id, pw, row.useRecovery)
        }
      }
      Button { text: "✕"; bordered: true; fontFamily: row.win.fontFamily; anchors.verticalCenter: parent.verticalCenter; onClicked: row.win.collapse() }
    }

    Text {
      visible: row.unlocking && row.encrypted
      textFormat: Text.PlainText
      text: row.useRecovery ? row.win.t("unlock.useNormal") : row.win.t("unlock.useRecovery")
      color: row.win.accent
      font.family: row.win.fontFamily
      font.pixelSize: Style.font.caption
      font.underline: true
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: { row.useRecovery = !row.useRecovery; unlockField.clear(); unlockField.forceActiveFocus() }
      }
    }

    // ---- cambio rápido de clave: actual + nueva ×2
    Column {
      visible: row.changing
      spacing: Style.space(6)
      PasswordField {
        id: oldField
        onValueChanged: if (row.service) row.service.touch()
        width: Style.space(340)
        height: Style.space(34)
        placeholder: row.win.t("passwd.old")
        nextField: newField
        onSubmitted: function(pw) { oldField.value = pw; newField.forceActiveFocus() }
        onEscaped: row.win.collapse()
      }
      PasswordField {
        id: newField
        onValueChanged: if (row.service) row.service.touch()
        width: Style.space(340)
        height: Style.space(34)
        placeholder: row.win.t("passwd.new")
        prevField: oldField
        nextField: new2Field
        onSubmitted: function(pw) { newField.value = pw; new2Field.forceActiveFocus() }
        onEscaped: row.win.collapse()
      }
      Row {
        spacing: Style.space(8)
        PasswordField {
          id: new2Field
          onValueChanged: if (row.service) row.service.touch()
          width: Style.space(340)
          height: Style.space(34)
          placeholder: row.win.t("passwd.new2")
          prevField: newField
          onSubmitted: function(pw) { new2Field.value = pw; row.submitPasswd() }
          onEscaped: row.win.collapse()
        }
        Button {
          text: row.busy ? row.win.t("passwd.busy") : row.win.t("passwd.change")
          bordered: true
          selected: true
          fontFamily: row.win.fontFamily
          anchors.verticalCenter: parent.verticalCenter
          onClicked: row.submitPasswd()
        }
        Button { text: "✕"; bordered: true; fontFamily: row.win.fontFamily; anchors.verticalCenter: parent.verticalCenter; onClicked: row.win.collapse() }
      }
    }

    Text {
      visible: row.error !== "" || row.notice !== ""
      textFormat: Text.PlainText
      text: row.error !== "" ? row.win.t(row.error.indexOf("form.") === 0 ? row.error : "error." + row.error) : row.notice
      color: row.error !== "" ? row.win.errorColor : row.win.openColor
      font.family: row.win.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}
