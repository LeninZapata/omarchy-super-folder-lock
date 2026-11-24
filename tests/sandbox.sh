#!/usr/bin/env bash
# Entorno de pruebas para el auxiliar: un $HOME y un $XDG_RUNTIME_DIR propios, para que
# folderlock.py nunca toque los datos ni las carpetas reales de Lenin.
#
#   tests/sandbox.sh new            → crea uno y escribe su ruta (base)
#   tests/sandbox.sh run BASE cmd…  → corre cmd con HOME=BASE/home y XDG_RUNTIME_DIR=BASE/run
#   tests/sandbox.sh clean BASE     → bloquea lo montado (fusermount3 -u -z) y lo borra
#   tests/sandbox.sh selftest       → gocryptfs -init + montar + escribir + desmontar
#
# Las claves de prueba son conocidas (no son de Lenin) y se pasan por stdin.
set -euo pipefail

new() {
  local base
  base=$(mktemp -d /tmp/sfl-sandbox.XXXXXX)
  mkdir -p "$base/home" "$base/run"
  chmod 700 "$base/home" "$base/run"
  echo "$base"
}

run() {
  local base="$1"; shift
  # Todas las XDG_* dentro del sandbox (la sesión de Lenin define XDG_CACHE_HOME y XDG_DATA_HOME).
  env -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_DATA_HOME -u XDG_STATE_HOME \
    HOME="$base/home" XDG_RUNTIME_DIR="$base/run" XDG_CACHE_HOME="$base/home/.cache" \
    XDG_DATA_HOME="$base/home/.local/share" XDG_CONFIG_HOME="$base/home/.config" \
    XDG_STATE_HOME="$base/home/.local/state" "$@"
}

clean() {
  local base="$1"
  case "$base" in /tmp/sfl-sandbox.*) ;; *) echo "no es un sandbox: $base" >&2; exit 1 ;; esac
  { grep -F " $base/" /proc/mounts || true; } | awk '{print $2}' | while read -r m; do fusermount3 -u -z "$m" || true; done
  rm -rf "$base"
}

selftest() {
  local base cipher plain
  base=$(new)
  cipher="$base/home/cipher"; plain="$base/home/plain"
  mkdir -p "$cipher" "$plain"
  printf 'test-key-123\n' | gocryptfs -init -q -passfile /dev/stdin "$cipher" >/dev/null
  printf 'test-key-123\n' | gocryptfs -q -passfile /dev/stdin "$cipher" "$plain"
  echo hola > "$plain/archivo.txt"
  grep -qF " $plain " /proc/mounts || { echo "selftest: no montó"; clean "$base"; exit 1; }
  fusermount3 -u "$plain"
  if [ -e "$plain/archivo.txt" ]; then echo "selftest: sigue legible tras desmontar"; clean "$base"; exit 1; fi
  local n
  n=$(find "$cipher" -type f ! -name 'gocryptfs.*' | wc -l)
  clean "$base"
  echo "sandbox ok (gocryptfs $(gocryptfs -version | awk '{print $2}' | tr -d ';'), $n archivo cifrado)"
}

case "${1:-}" in
  new) new ;;
  run) shift; run "$@" ;;
  clean) clean "$2" ;;
  selftest) selftest ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
