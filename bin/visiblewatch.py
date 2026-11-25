#!/usr/bin/env python3
"""Vigilante del modo visible (ESQUEMA M6, decidido con Lenin el 2026-11-23).

Una carpeta VISIBLE bloqueada queda vacía en su sitio. Cuando alguien entra en ella con
doble clic, Nautilus abre el directorio (IN_OPEN) Y su ventana pasa a llamarse como la
carpeta. Lo primero solo no basta: el indexador (localsearch), `find` o `ls` también la
abren. Por eso se avisa SOLO si en ±1,5 s aparece una ventana de Nautilus con ese nombre.
Y no cuenta la ventana que YA estaba dentro cuando se bloqueó: al bloquearse, Nautilus vuelve
a leer la carpeta y ya se llama como ella (pedía la clave sin doble clic, 2026-11-25).

Uso: python3 -I visiblewatch.py      (lo lanza Service.qml y lo mantiene vivo)
Salida, una línea por petición:  open <id> <address-de-la-ventana>   (sin nombres ni rutas)
Lee el registro y los montajes él mismo (como el auxiliar): el servicio no necesita cargar
el registro sin pasar la puerta. Se re-sincroniza cuando cambian el registro o los montajes.
"""
import ctypes
import ctypes.util
import json
import os
import select
import shutil
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import folderlock  # noqa: E402  (mismo directorio; -I no lo añade solo)

IN_ACCESS, IN_CLOSE_WRITE, IN_OPEN = 0x1, 0x8, 0x20
IN_MOVED_TO, IN_CREATE, IN_DELETE = 0x80, 0x100, 0x200
IN_ONLYDIR, IN_IGNORED = 0x01000000, 0x8000
EVENT = struct.Struct("iIII")

CONFIRM_SECONDS = 1.5
QUIET_SECONDS = 3.0
INSIDE_POLL_SECONDS = 1.0
FILE_MANAGERS = ("org.gnome.nautilus", "nautilus")


def hyprctl_clients():
    cmd = os.environ.get("SFL_HYPRCTL") or shutil.which("hyprctl") or "hyprctl"
    try:
        out = subprocess.run([cmd, "clients", "-j"], capture_output=True, timeout=2).stdout
        return json.loads(out or b"[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def folder_name(path):
    return os.path.basename(path.rstrip("/"))


def windows_named(name, clients=None):
    """Direcciones de las ventanas del gestor de archivos que se llaman como la carpeta."""
    return {str(c.get("address", "")) for c in (hyprctl_clients() if clients is None else clients)
            if str(c.get("class", "")).lower() in FILE_MANAGERS and c.get("title") == name}


def find_window(name, skip=()):
    """Una ventana del gestor que ya se llama como la carpeta y no estaba ya dentro."""
    for addr in sorted(windows_named(name) - set(skip)):
        return addr
    return None


def visible_locked():
    """{path: id} de las carpetas VISIBLES que están bloqueadas (sin montaje vivo)."""
    try:
        folders = folderlock.read_registry()["folders"]
    except folderlock.Fail:
        return {}
    out = {}
    for fid, f in folders.items():
        if f.get("mode") != "visible" or not f.get("path"):
            continue
        if folderlock.is_open(fid, f):
            continue
        out[f["path"]] = fid
    return out


class Watcher:
    def __init__(self):
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self.libc = libc
        self.fd = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self.folders = {}   # wd -> (id, path)
        self.meta = set()   # wd de la carpeta de datos y la de montajes
        self.quiet = {}     # id -> hasta cuándo no se vuelve a avisar
        # id -> ventanas que ya estaban dentro (al bloquearse, o tras avisar): sus relecturas
        # no son un doble clic. Salen del conjunto en cuanto dejan de llamarse como la carpeta.
        self.inside = {}
        self.dirty = True
        self.removed = set()

    def add(self, path, mask):
        wd = self.libc.inotify_add_watch(self.fd, path.encode(), mask)
        return wd if wd >= 0 else None

    def resync(self):
        # Las carpetas de datos y de montajes se vigilan una sola vez; las de las carpetas
        # visibles se rehacen (quitar uno genera IN_IGNORED: se descarta abajo, sin bucle).
        if not self.meta:
            for d in (folderlock.data_dir(), folderlock.run_dir()):
                os.makedirs(d, mode=0o700, exist_ok=True)
                wd = self.add(d, IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_ONLYDIR)
                if wd is not None:
                    self.meta.add(wd)
        for wd in list(self.folders):
            self.libc.inotify_rm_watch(self.fd, wd)
        self.removed = set(self.folders)
        watched_before = {fid for fid, _ in self.folders.values()}
        self.folders = {}
        missing = False
        clients = None
        inside = {}
        for path, fid in visible_locked().items():
            wd = self.add(path, IN_OPEN | IN_ONLYDIR)
            if wd is not None:
                self.folders[wd] = (fid, path)
            else:
                missing = True
            if fid in watched_before:
                if self.inside.get(fid):
                    inside[fid] = self.inside[fid]
            else:
                # Recién bloqueada: la ventana que la tenía abierta sigue dentro.
                if clients is None:
                    clients = hyprctl_clients()
                now = windows_named(folder_name(path), clients)
                if now:
                    inside[fid] = now
        self.inside = inside
        # Una carpeta visible cuya ruta aún no existe (se está creando o la movieron): se
        # vuelve a intentar en la próxima vuelta (cada 5 s como mucho).
        self.dirty = missing
        if os.environ.get("SFL_WATCH_DEBUG"):
            print("resync %s" % sorted(f[0] for f in self.folders.values()), file=sys.stderr, flush=True)

    def events(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        try:
            buf = os.read(self.fd, 65536)
        except BlockingIOError:
            return []
        out, i = [], 0
        while i + EVENT.size <= len(buf):
            wd, mask, _cookie, length = EVENT.unpack_from(buf, i)
            i += EVENT.size + length
            out.append((wd, mask))
        return out

    def prune_inside(self):
        """Olvida las ventanas que ya salieron de la carpeta (otro título o cerradas)."""
        if not self.inside:
            return
        clients = hyprctl_clients()
        names = {fid: folder_name(path) for fid, path in self.folders.values()}
        self.inside = {fid: keep for fid, addrs in self.inside.items()
                       if fid in names and (keep := addrs & windows_named(names[fid], clients))}

    def confirm(self, fid, path):
        """El IN_OPEN vale solo si aparece la ventana del gestor con el nombre de la carpeta."""
        name = folder_name(path)
        end = time.time() + CONFIRM_SECONDS
        while time.time() < end:
            addr = find_window(name, self.inside.get(fid, ()))
            if addr is not None:
                return addr
            time.sleep(0.2)
        return None

    def run(self):
        while True:
            if self.dirty:
                self.resync()
            # Con alguna ventana dentro, se mira cada segundo si ya salió: si sale y vuelve a
            # entrar con doble clic, ese sí cuenta.
            self.prune_inside()
            for wd, mask in self.events(INSIDE_POLL_SECONDS if self.inside else 5.0):
                if wd in self.meta:
                    self.dirty = True
                    continue
                if mask & IN_IGNORED:
                    # la carpeta vigilada desapareció o se montó encima: re-sincronizar; el
                    # IN_IGNORED de un vigilante quitado por resync() no cuenta
                    if wd in self.folders:
                        self.dirty = True
                    continue
                if not mask & IN_OPEN or wd not in self.folders:
                    continue
                fid, path = self.folders[wd]
                if self.quiet.get(fid, 0) > time.time():
                    continue
                addr = self.confirm(fid, path)
                if addr is not None:
                    self.quiet[fid] = time.time() + QUIET_SECONDS
                    self.inside.setdefault(fid, set()).add(addr)
                    print("open %s %s" % (fid, addr), flush=True)


if __name__ == "__main__":
    try:
        Watcher().run()
    except KeyboardInterrupt:
        pass
