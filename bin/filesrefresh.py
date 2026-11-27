#!/usr/bin/env python3
"""Refresca las ventanas de Files que muestran una carpeta recién desbloqueada o bloqueada.

Al desbloquear, la carpeta con archivos ocupa el sitio de la vacía, pero Nautilus no se entera:
las ventanas que ya la mostraban seguían «vacías» hasta pulsar F5 (2026-11-25). Al bloquear, al
revés: seguían enseñando los archivos (2026-11-27; lo lanza folderlock.py). Se les manda esa
tecla por Hyprland, sin cambiar el foco ni el workspace. Va por el título (solo el nombre): si
otra carpeta se llama igual, también se recarga, que no cambia nada. Las pestañas de detrás no.

Uso: python3 -I filesrefresh.py <ruta>      (lo lanzan Service.qml y folderlock.py)
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import visiblewatch  # noqa: E402  (mismo directorio; -I no lo añade solo)


def refresh(path):
    cmd = os.environ.get("SFL_HYPRCTL") or shutil.which("hyprctl") or "hyprctl"
    for addr in sorted(visiblewatch.windows_named(visiblewatch.folder_name(path))):
        if not re.fullmatch(r"0x[0-9a-f]+", addr):
            continue
        try:
            subprocess.run([cmd, "dispatch", 'hl.dsp.send_shortcut({ mods = "", key = "F5", window = "address:%s" })' % addr],
                           capture_output=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


if __name__ == "__main__":
    if len(sys.argv) == 2:
        refresh(sys.argv[1])
