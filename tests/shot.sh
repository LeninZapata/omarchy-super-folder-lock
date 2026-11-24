#!/usr/bin/env bash
# Captura la ventana de Super Folder Lock (o la ventana cuyo título empiece por $2),
# recortada a su geometría. Uso: tests/shot.sh [salida.png] [título]
# Sale con 2 si no hay ventana con ese título.
set -euo pipefail
out="${1:-/tmp/sfl-shot.png}"
title="${2:-Super Folder Lock}"
geom=$(hyprctl clients -j | python3 -I -c '
import json, sys
t = sys.argv[1]
for c in json.load(sys.stdin):
    if c.get("title", "").startswith(t):
        x, y = c["at"]; w, h = c["size"]
        print("%d,%d %dx%d" % (x, y, w, h)); sys.exit()
' "$title")
if [ -z "$geom" ]; then echo "no hay ventana «$title»"; exit 2; fi
grim -g "$geom" "$out"
echo "$out ($geom)"
