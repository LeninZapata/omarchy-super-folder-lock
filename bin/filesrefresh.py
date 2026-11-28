#!/usr/bin/env python3
"""Refresca las ventanas de Files que muestran una carpeta recién desbloqueada o bloqueada.

Al desbloquear, la carpeta con archivos ocupa el sitio de la vacía, pero Nautilus no se entera:
las ventanas que ya la mostraban seguían «vacías» hasta pulsar F5 (2026-11-25). Al bloquear, al
revés: seguían enseñando los archivos (2026-11-27; lo lanza folderlock.py). Se les manda esa
tecla por Hyprland, sin cambiar el foco ni el workspace. Va por el título (solo el nombre): si
otra carpeta se llama igual, también se recarga, que no cambia nada. Las pestañas de detrás no.
Entran también las ventanas que estaban en una subcarpeta (Files dice por D-Bus qué ruta muestra
cada una, 2026-11-28): con el F5, Files sube a la carpeta (o más arriba, si ya no existe).

Con --open (desbloquear con «Mostrar la carpeta»), además la abre en Files, pero SOLO si ninguna
ventana la estaba mostrando ya: si no, quedaban dos iguales, la refrescada y la nueva (2026-11-28).
Eso lo dice Files por D-Bus (la ruta exacta, no el título); si no responde, se abre como antes.

Uso: python3 -I filesrefresh.py [--open] <ruta>      (lo lanzan Service.qml y folderlock.py)
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
    for addr in sorted(visiblewatch.windows_showing(path)):
        if not re.fullmatch(r"0x[0-9a-f]+", addr):
            continue
        try:
            subprocess.run([cmd, "dispatch", 'hl.dsp.send_shortcut({ mods = "", key = "F5", window = "address:%s" })' % addr],
                           capture_output=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def shown(path):
    """¿Alguna ventana o pestaña de Files muestra ya la carpeta o algo dentro de ella?"""
    root = path.rstrip("/")
    return any(p.rstrip("/") == root or p.startswith(root + "/") for p in visiblewatch.file_manager_locations())


if __name__ == "__main__":
    args = sys.argv[1:]
    want_open = args[:1] == ["--open"]
    if want_open:
        args = args[1:]
    if len(args) == 1:
        already = want_open and shown(args[0])   # antes del F5: luego Files podría cambiar de ruta
        refresh(args[0])
        if want_open and not already:
            cmd = os.environ.get("SFL_XDG_OPEN") or "xdg-open"
            try:
                os.execvp(cmd, [cmd, args[0]])
            except OSError:
                sys.exit(1)
