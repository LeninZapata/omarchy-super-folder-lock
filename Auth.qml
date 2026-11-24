import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pam
import "Core.js" as Core

// Puerta de la ventana: la clave del sistema por PAM (omarchy-lock-password, con
// faillock). Adaptado de Super Workspace Lock sin la rama de clave propia. La clave
// solo vive en `pending` hasta entregarla a PAM y se borra en cuanto se usa o falla.
// Nunca va a un argumento ni a un log. Nunca se toca /etc/pam.d.
Item {
  id: auth

  // Los de /etc/pam.d/omarchy-lock-password (deny=10 unlock_time=120).
  readonly property int faillockDeny: 10
  readonly property int faillockUnlockSec: 120
  readonly property string userName: Quickshell.env("USER") || Quickshell.env("LOGNAME")

  property bool busy: false
  property string pending: ""

  signal succeeded()
  // left = intentos que quedan antes de faillock · wait > 0: hay que esperar.
  signal failed(int left, int wait)

  function submit(password) {
    if (busy || !password || password.length === 0) return
    pending = password
    busy = true
    if (!pam.start()) finishFailure()
    else Qt.callLater(respond)
  }

  function respond() {
    if (!busy || !pam.active || !pam.responseRequired) return
    pam.respond(pending)
    pending = ""
  }

  function finishFailure() {
    pending = ""
    faillockProc.exec(["faillock", "--user", userName])
  }

  PamContext {
    id: pam
    config: "omarchy-lock-password"
    user: auth.userName

    onResponseRequiredChanged: auth.respond()
    onPamMessage: auth.respond()
    onCompleted: function(result) {
      auth.pending = ""
      if (result === PamResult.Success) {
        auth.busy = false
        auth.succeeded()
      } else auth.finishFailure()
    }
    onError: function(error) { auth.finishFailure() }
  }

  // Tras un fallo: ¿cuántos quedan y ya saltó faillock? (el propio usuario lo lee sin root)
  Process {
    id: faillockProc
    stdout: StdioCollector {
      onStreamFinished: {
        auth.busy = false
        var info = Core.faillockInfo(text, Date.now(), auth.faillockDeny, auth.faillockUnlockSec)
        auth.failed(info.left, info.wait)
      }
    }
  }
}
