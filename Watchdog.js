.pragma library
// Vigía (ESQUEMA M2.T5): un proceso aparte que espera la muerte del shell y bloquea todo.
// El daemon de gocryptfs vive fuera del shell: sin esto, una carpeta abierta seguiría
// abierta tras un crash o un `omarchy restart shell`, sin nadie que la cierre.
//
// - Lo lanza el servicio con execDetached (sobrevive al shell) al abrir una carpeta y,
//   mientras haya alguna abierta, cada 30 s: si murió, vuelve a nacer.
// - Uno solo a la vez: `flock -n` sobre watchdog.lock; el repetido sale en el acto.
// - Sale solo cuando ya no queda ninguna abierta (ningún mount-*.json).

function command(shellPid, helperPath, runDir) {
  var pid = Math.round(Number(shellPid) || 0)
  if (!(pid > 1) || !helperPath || !runDir) return null
  var script =
    'umask 077; pid="$1"; helper="$2"; dir="$3"; mkdir -p "$dir" && chmod 700 "$dir" || exit 0; '
    + 'exec 9>"$dir/watchdog.lock"; flock -n 9 || exit 0; '
    + 'while kill -0 "$pid" 2>/dev/null; do '
    + 'set -- "$dir"/mount-*.json; [ -e "$1" ] || exit 0; sleep 1; done; '
    + 'python3 -I "$helper" lockall >/dev/null 2>&1'
  return ["sh", "-c", script, "sfl-watchdog", String(pid), helperPath, runDir]
}
