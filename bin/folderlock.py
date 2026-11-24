#!/usr/bin/env python3
"""Auxiliar de Super Folder Lock: el ÚNICO que toca gocryptfs, el registro y los montajes.

Uso (siempre con `python3 -I`):  folderlock.py <subcomando> [id]
  list            el registro (solo lo pide el servicio tras la puerta PAM)
  status          carpetas abiertas (ids) y total; limpia los restos
  unlock <id> [recovery]
                  clave por stdin → mkdir + montar + mount-<id>.json; con «recovery» lo que
                  llega es la clave de recuperación (gocryptfs -masterkey=stdin)
  lock <id>       SIGTERM al daemon (si es el mismo proceso) → desmontar → rmdir
  lockall         lock de todo lo montado (vigía y arranque)
  update <id>     stdin: JSON {name, rules} → cambia nombre y reglas (no ruta ni clave)
  passwd <id>     stdin: línea 1 = clave actual, línea 2 = nueva → gocryptfs -passwd
                  (reescribe solo gocryptfs.conf; vale con la carpeta abierta)
  holders <id>    qué programas tienen archivos abiertos (o su cwd) dentro de una abierta
                  → {apps: [nombres]}; nunca qué archivos
  check           stdin: JSON {path} → {state: new|empty} o el error de esa ruta (formulario)
  unprotect <id>  clave por stdin → saca los archivos a una carpeta normal en su ruta, los
                  compara uno a uno con los cifrados y SOLO ENTONCES quita la bóveda
  orphans         ids de bóvedas en vaults/ que no están en el registro (sin nombres)
  readd <id|any>  stdin: línea 1 = clave, línea 2 = JSON {path, name, mode, rules} → la clave
                  se comprueba (con «any», dice cuál de las sin registrar es) y vuelve al registro
  forget <id>     quita del registro una entrada cuyos archivos YA NO EXISTEN (nunca una con contenido)
  destroy <id>    bloquea si hace falta y BORRA la bóveda y su entrada (sin vuelta atrás)
  info <id>       solo el nombre (la tarjeta del modo visible; no carga el listado)
  init            stdin: línea 1 = clave, línea 2 = JSON {path, name, rules} → crea
                  la bóveda nueva y devuelve la clave de recuperación (se enseña UNA vez)

Dos tipos de carpeta (campo `type` del registro; sin él, "encrypt"):
  hide      la carpeta se MUEVE (rename, mismo disco) a un almacén sin permisos. No se copia ni
            se cambia nada; tarda lo mismo con 1 MB que con 1 TB. No está cifrada.
  encrypt   bóveda de gocryptfs.

Salida: UNA línea JSON {"ok": bool, "error": "<clave i18n>" | null, "data": {...}}.
Las claves entran SOLO por stdin: nunca en argumentos, logs ni salida (ver CLAUDE.md).
Solo biblioteca estándar. Modelo de datos: DATOS.md.
"""
import fcntl
import hashlib
import hmac
import html
import json
import os
import secrets
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zlib

HEADER = "SFLDB 1 — do not edit; managed by Super Folder Lock"
ID_RE = re.compile(r"^[0-9a-f]{16}$")


class Fail(Exception):
    """Error con su clave i18n (`error.<key>` en i18n/)."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


# ------------------------------------------------------------------ rutas
def data_dir():
    return os.path.join(os.path.expanduser("~"), ".local", "share", "omarchy", "super-folder-lock")


# Fuera de $HOME solo valen discos montados aquí; lo cifrado se queda en ESE disco.
DISK_DIR = ".super-folder-lock"


def media_roots():
    return ["/run/media/%s" % os.path.basename(os.path.expanduser("~")), "/media", "/mnt"]


def disk_root(path):
    """Punto de montaje del disco externo que contiene `path`, o None."""
    for root in media_roots():
        if path == root or not path.startswith(root + "/"):
            continue
        cur = path
        while cur != root:
            if os.path.ismount(cur):
                return cur
            cur = os.path.dirname(cur)
    return None


def disk_vaults(root):
    return os.path.join(root, DISK_DIR, "vaults")


def mounted_disks():
    return sorted({m for m in mounted_points() for r in media_roots() if m.startswith(r + "/")})


def default_vault(fid):
    return os.path.join(data_dir(), "vaults", fid)


def vault_dir(fid):
    """Donde vive lo cifrado: el registro manda (disco externo); si no está en él, se busca
    en la carpeta de datos y en los discos conectados (bóvedas sin registrar)."""
    try:
        folder = read_registry()["folders"].get(fid) or {}
    except Fail:
        folder = {}
    v = folder.get("vault")
    # El registro se puede editar a mano y `destroy` borra esta ruta: solo se acepta con su forma.
    if isinstance(v, str) and v.startswith("/") and v.endswith("/%s/vaults/%s" % (DISK_DIR, fid)) and ".." not in v.split("/"):
        return v
    local = default_vault(fid)
    if folder or os.path.isdir(local):
        return local
    for root in mounted_disks():
        cand = os.path.join(disk_vaults(root), fid)
        if os.path.isdir(cand) and not os.path.islink(cand):
            return cand
    return local


def require_vault(fid):
    """La bóveda está a mano; si es de un disco que no está conectado, se dice así."""
    v = vault_dir(fid)
    if not os.path.isfile(os.path.join(v, "gocryptfs.conf")):
        raise Fail("disk.missing" if v != default_vault(fid) else "vault.missing")
    return v


def registry_path():
    return os.path.join(data_dir(), "folders.sfldb")


def run_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(base, "super-folder-lock")


def mount_file(fid):
    return os.path.join(run_dir(), "mount-%s.json" % fid)


def ensure_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def harden():
    """Carpeta de datos 700 y archivos 600, también lo que ya existía (M1.T1.S2)."""
    base = data_dir()
    if not os.path.isdir(base):
        return
    os.chmod(base, 0o700)
    for root, dirs, files in os.walk(base):
        if os.path.relpath(root, base).split(os.sep)[0] in ("locked", "strays") and root != os.path.join(base, "locked"):
            dirs[:] = []  # contenido de Lenin: no se le toca ni un permiso
            continue
        if root == os.path.join(base, "locked"):
            for n in files:
                os.chmod(os.path.join(root, n), 0o600)
            dirs[:] = []
            continue
        if os.path.relpath(root, base).split(os.sep)[0] == "vaults" and root != os.path.join(base, "vaults"):
            dirs[:] = []  # dentro de cada bóveda manda gocryptfs
            continue
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o700)
        for f in files:
            os.chmod(os.path.join(root, f), 0o600)


# ------------------------------------------------------------------ archivos
def write_atomic(path, text):
    """Temporal 600 en la misma carpeta + rename: nunca un archivo a medias."""
    folder = os.path.dirname(path)
    ensure_dir(folder)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_registry():
    """Falta = registro vacío. Roto = error, y NO se pisa."""
    try:
        with open(registry_path(), encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"schemaVersion": 1, "folders": {}}
    first, _, rest = raw.partition("\n")
    if not first.startswith("SFLDB "):
        raise Fail("registry.broken")
    try:
        reg = json.loads(rest)
    except ValueError:
        raise Fail("registry.broken")
    if not isinstance(reg, dict) or not isinstance(reg.get("folders"), dict):
        raise Fail("registry.broken")
    return reg


def is_hide(f):
    return f.get("type") == "hide"


def write_registry(reg):
    write_atomic(registry_path(), HEADER + "\n" + json.dumps(reg, indent=2, ensure_ascii=False) + "\n")


def get_folder(fid):
    if not ID_RE.match(fid or ""):
        raise Fail("folder.unknown")
    folder = read_registry()["folders"].get(fid)
    if not folder:
        raise Fail("folder.unknown")
    return folder


# ------------------------------------------------------------------ procesos y montajes
def unescape_mount(s):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def mounted_points():
    out = set()
    with open("/proc/mounts", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3:
                out.add(unescape_mount(parts[1]))
    return out


def pid_start_time(pid):
    """Campo 22 de /proc/<pid>/stat (tras el nombre entre paréntesis). None si no existe."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as f:
            stat = f.read()
    except (OSError, ValueError):
        return None
    fields = stat[stat.rindex(")") + 2:].split()
    return int(fields[19])


def find_daemon(mountpoint):
    """El daemon de gocryptfs que sirve ese punto: se relanza a sí mismo con -fg."""
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % name, "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == "gocryptfs" and "-fg" in argv and argv[-1] == mountpoint:
            return int(name)
    return None


def read_mount(fid):
    try:
        with open(mount_file(fid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def mount_alive(info):
    """El proceso es el MISMO que montó (pid + hora de arranque) y el punto sigue montado."""
    pid = info.get("pid")
    if not isinstance(pid, int) or pid_start_time(pid) != info.get("pidStartTime"):
        return False
    return info.get("mountPoint") in mounted_points()


def remove_empty_dir(path):
    try:
        os.rmdir(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


# ------------------------------------------------------------------ rastros en claro (H4)
def _uri_inside(uri, path):
    if not uri.startswith("file://"):
        return False
    local = urllib.parse.unquote(uri[len("file://"):])
    return local == path or local.startswith(path.rstrip("/") + "/")


def png_thumb_uri(file_path):
    """El texto `Thumb::URI` de una miniatura PNG (tEXt, o zTXt/iTXt sin comprimir), o None."""
    try:
        with open(file_path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            while True:
                head = f.read(8)
                if len(head) < 8:
                    return None
                size = int.from_bytes(head[:4], "big")
                kind = head[4:8]
                if kind == b"IDAT" or kind == b"IEND" or size > 1 << 20:
                    return None
                body = f.read(size)
                f.read(4)  # CRC
                if kind == b"tEXt":
                    key, _, val = body.partition(b"\0")
                    if key == b"Thumb::URI":
                        return val.decode("latin-1")
                elif kind == b"iTXt":
                    key, _, rest = body.partition(b"\0")
                    if key == b"Thumb::URI" and len(rest) >= 2:
                        flag, rest = rest[0], rest[2:]
                        _lang, _, rest = rest.partition(b"\0")
                        _tkey, _, val = rest.partition(b"\0")
                        return (zlib.decompress(val) if flag else val).decode("utf-8", "replace")
    except OSError:
        return None


def clean_thumbnails(path):
    """Borra las miniaturas (freedesktop) de archivos que estaban dentro de `path`."""
    base = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "thumbnails")
    removed = 0
    for root, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith(".png"):
                continue
            full = os.path.join(root, name)
            uri = png_thumb_uri(full)
            if uri and _uri_inside(uri, path):
                try:
                    os.unlink(full)
                    removed += 1
                except OSError:
                    pass
    return removed


BOOKMARK_RE = re.compile(r'[ \t]*<bookmark\s[^>]*?href="([^"]*)".*?</bookmark>[ \t]*\n?', re.S)


def clean_recent(path):
    """Quita de recently-used.xbel (GTK) las entradas dentro de `path`; el resto, intacto."""
    xbel = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
                        "recently-used.xbel")
    try:
        with open(xbel, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return 0
    removed = [0]

    def drop(m):
        if _uri_inside(html.unescape(m.group(1)), path):
            removed[0] += 1
            return ""
        return m.group(0)

    new = BOOKMARK_RE.sub(drop, text)
    if removed[0]:
        mode = os.stat(xbel).st_mode & 0o777
        folder = os.path.dirname(xbel)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".recently-used.")
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new)
            os.replace(tmp, xbel)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return removed[0]


# ------------------------------------------------------------------ crear (init)
# Testigo dentro de cada carpeta cifrada: `-masterkey` monta con CUALQUIER clave (no la
# verifica, comprobado 2026-11-23); con una mal escrita, lo guardado quedaría cifrado con una
# clave equivocada. Al abrir con la de recuperación, si el testigo no se lee, se desmonta.
CHECK_NAME = ".super-folder-lock"
CHECK_TEXT = "Super Folder Lock — check file. Do not delete.\n"


def write_check(path):
    target = os.path.join(path, CHECK_NAME)
    try:
        with open(target, encoding="utf-8") as f:
            if f.read() == CHECK_TEXT:
                return
    except OSError:
        pass
    with open(target, "w", encoding="utf-8") as f:
        f.write(CHECK_TEXT)


def recovery_verdict(fid, path):
    """ok | wrong | unverifiable — tras montar con la clave de recuperación."""
    try:
        with open(os.path.join(path, CHECK_NAME), encoding="utf-8") as f:
            return "ok" if f.read() == CHECK_TEXT else "wrong"
    except (OSError, UnicodeDecodeError):
        pass
    cipher = [n for n in os.listdir(vault_dir(fid)) if not n.startswith("gocryptfs.")]
    if not cipher:
        return "unverifiable"
    return "ok" if os.listdir(path) else "wrong"   # nombres que no se descifran no aparecen


def unmount_now(path):
    pid = find_daemon(path)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(60):
            if path not in mounted_points():
                break
            time.sleep(0.05)
    if path in mounted_points():
        subprocess.run(["fusermount3", "-u", "-z", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


RULE_KEYS = ("idleLock", "workspaceLock", "screenLock", "openInFileManager", "maxOpenLock")
MIN_KEY = 5


def clean_rules(raw):
    """Solo reglas conocidas y válidas; lo demás se descarta (DATOS.md)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: raw.get(k) if raw.get(k) in ("inherit", "off", "on") else "inherit" for k in RULE_KEYS}
    sec = raw.get("idleSeconds")
    out["idleSeconds"] = sec if isinstance(sec, int) and not isinstance(sec, bool) and 60 <= sec <= 7200 else None
    mx = raw.get("maxOpenSeconds")
    out["maxOpenSeconds"] = mx if isinstance(mx, int) and not isinstance(mx, bool) and 300 <= mx <= 86400 else None
    return out


def validate_new_path(path, reg, full=False):
    """Ruta nueva: absoluta, dentro de $HOME, sin enlaces, no existe o vacía, sin cruzarse
    con otra carpeta protegida ni con la carpeta de datos del plugin."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise Fail("path.invalid")
    path = os.path.normpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise Fail("path.parentMissing")
    in_home = parent == home or parent.startswith(home + "/")
    disk = None if in_home else disk_root(parent)
    if os.path.realpath(parent) != parent or not (in_home or disk) or path == home:
        raise Fail("path.outsideHome")
    if disk and not os.access(disk, os.W_OK):
        raise Fail("disk.readOnly")
    if os.path.lexists(path):
        if os.path.islink(path) or not os.path.isdir(path):
            raise Fail("path.notEmpty")
        if os.listdir(path) and not full:
            raise Fail("path.notEmpty")
        # Con archivos: ni un punto de montaje ni carpetas de configuración (~/.algo).
        if full and (os.path.ismount(path) or (in_home and path[len(home) + 1:].startswith("."))):
            raise Fail("path.system")
    data = data_dir()
    for other in [data] + ([os.path.join(disk, DISK_DIR)] if disk else []) + [f.get("path", "") for f in reg["folders"].values()]:
        if not other:
            continue
        if path == other or path.startswith(other + "/") or other.startswith(path + "/"):
            raise Fail("path.taken")
    return path


def format_master_key(hexkey):
    hexkey = hexkey.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", hexkey):
        raise Fail("init.failed")
    return "-".join(hexkey[i:i + 8] for i in range(0, 64, 8))


def cmd_init(_args):
    key = sys.stdin.readline().rstrip("\n")
    try:
        meta = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        raise Fail("init.failed")
    if len(key) < MIN_KEY:
        raise Fail("key.short")
    reg = read_registry()
    if meta.get("type") == "hide":
        return hide_init(reg, meta, key)
    if not shutil.which("gocryptfs") or not shutil.which("gocryptfs-xray"):
        raise Fail("gocryptfs.missing")
    path = validate_new_path(meta.get("path"), reg)
    name = str(meta.get("name") or "").strip()[:60] or os.path.basename(path)
    mode = "visible" if meta.get("mode") == "visible" else "hidden"
    disk = disk_root(os.path.dirname(path))
    base = disk_vaults(disk) if disk else os.path.join(data_dir(), "vaults")
    ensure_dir(data_dir())
    if disk:
        ensure_dir(os.path.join(disk, DISK_DIR))
    ensure_dir(base)
    fid = secrets.token_hex(8)
    while fid in reg["folders"] or os.path.exists(os.path.join(base, fid)):
        fid = secrets.token_hex(8)
    vault = os.path.join(base, fid)
    os.mkdir(vault, 0o700)
    had_dir = os.path.isdir(path)
    try:
        p = subprocess.run(["gocryptfs", "-init", "-q", "-passfile", "/dev/stdin", vault],
                           input=(key + "\n").encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.returncode != 0:
            raise Fail("init.failed")
        x = subprocess.run(["gocryptfs-xray", "-dumpmasterkey", os.path.join(vault, "gocryptfs.conf")],
                           input=(key + "\n").encode(), capture_output=True)
        key_for_check, key = key, ""
        if x.returncode != 0:
            raise Fail("init.failed")
        recovery = format_master_key(x.stdout.decode("ascii", "replace").strip().splitlines()[-1])
        # El testigo, con un montaje temporal dentro de la carpeta de datos (700).
        tmp = tempfile.mkdtemp(prefix=".init-", dir=data_dir())
        try:
            m = subprocess.run(["gocryptfs", "-q", "-passfile", "/dev/stdin", vault, tmp],
                               input=(key_for_check + "\n").encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if m.returncode != 0:
                raise Fail("init.failed")
            write_check(tmp)
        finally:
            unmount_now(tmp)
            remove_empty_dir(tmp)
        key_for_check = ""
        reg["folders"][fid] = dict({
            "name": name,
            "path": path,
            "type": "encrypt",
            "mode": mode,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }, **clean_rules(meta.get("rules")))
        if disk:
            reg["folders"][fid]["vault"] = vault
        # Bloqueada: oculta = la ruta no existe; visible = carpeta vacía en su sitio. ANTES de
        # escribir el registro: el vigilante del modo visible se resincroniza con ese cambio y
        # necesita la carpeta ya creada.
        if mode == "visible":
            if not os.path.lexists(path):
                os.mkdir(path, 0o700)
        elif os.path.isdir(path) and not os.path.islink(path):
            os.rmdir(path)
        write_registry(reg)
    except BaseException:
        shutil.rmtree(vault, ignore_errors=True)
        if disk:
            drop_disk_dir(vault)
        if had_dir and not os.path.exists(path):
            os.mkdir(path, 0o700)  # deshacer: la carpeta vacía de Lenin vuelve a estar
        raise
    return {"id": fid, "name": name, "path": path, "recoveryKey": recovery}


# ------------------------------------------------------------------ tipo «esconder»
# Invariante: el contenido está SIEMPRE en un solo sitio, su ruta o <almacén>/data, y solo se
# mueve con os.rename (atómico, mismo disco). Aquí no se copia ni se borra contenido jamás.
# Almacén: <carpeta de datos o <disco>/.super-folder-lock>/locked/<id>/, con permisos 000.
# Al lado, <id>.json con la huella de la clave (sin nombre ni ruta), por si se pierde el registro.
def hide_base(path):
    disk = disk_root(os.path.dirname(path))
    return os.path.join(os.path.join(disk, DISK_DIR) if disk else data_dir(), "locked")


def hide_store(fid, f):
    return os.path.join(hide_base(f["path"]), fid)


def hide_locked(store):
    try:
        st = os.lstat(store)
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    # Sin permisos = guardada. Con ellos (disco que no los guarda, o un corte a mitad), lo dice data/.
    return not st.st_mode & 0o700 or os.path.isdir(os.path.join(store, "data"))


def hide_open(fid, f):
    return not hide_locked(hide_store(fid, f)) and os.path.isdir(f["path"]) and not os.path.islink(f["path"])


def is_open(fid, f):
    if is_hide(f):
        return hide_open(fid, f)
    info = read_mount(fid)
    return bool(info and mount_alive(info))


def key_hash(key):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(key.encode(), salt=salt, n=1 << 14, r=8, p=1, dklen=32)
    return {"algo": "scrypt", "n": 1 << 14, "r": 8, "p": 1, "salt": salt.hex(), "hash": h.hex()}


def key_ok(auth, key):
    try:
        if auth["algo"] != "scrypt":
            return False
        h = hashlib.scrypt(key.encode(), salt=bytes.fromhex(auth["salt"]), n=int(auth["n"]), r=int(auth["r"]),
                           p=int(auth["p"]), dklen=32, maxmem=1 << 27)
        return hmac.compare_digest(h.hex(), auth["hash"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def shut(store, mode=0o000):
    try:
        os.chmod(store, mode)
    except OSError:
        pass  # discos sin permisos (exFAT): queda escondida igual


def hide_device_ok(path):
    """Mover (sin copiar) exige el mismo sistema de archivos que el almacén."""
    base = hide_base(path)
    probe = base
    while not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    here = path if os.path.isdir(path) else os.path.dirname(path)
    return os.lstat(here).st_dev == os.lstat(probe).st_dev


def write_auth(fid, f):
    ensure_dir(hide_base(f["path"]))
    # Solo si cambió: el fsync en un disco lento haría esperar en cada bloqueo.
    try:
        with open(hide_store(fid, f) + ".json", encoding="utf-8") as fh:
            if json.load(fh).get("auth") == f["auth"]:
                return
    except (OSError, ValueError, AttributeError):
        pass
    write_atomic(hide_store(fid, f) + ".json", json.dumps({"id": fid, "auth": f["auth"]}) + "\n")


def hide_settle(fid, f):
    """Guardada: oculta = su ruta no existe; visible = carpeta vacía en su sitio."""
    path = f["path"]
    if f.get("mode") == "visible":
        if not os.path.lexists(path) and os.path.isdir(os.path.dirname(path)):
            os.mkdir(path, 0o700)
    elif os.path.isdir(path) and not os.path.islink(path):
        remove_empty_dir(path)


def drop_mount_file(fid):
    try:
        os.unlink(mount_file(fid))
    except FileNotFoundError:
        pass


def hide_lock(fid, f):
    path, store = f["path"], hide_store(fid, f)
    if hide_locked(store):
        shut(store)
        hide_settle(fid, f)
        drop_mount_file(fid)
        return False
    if not os.path.isdir(path) or os.path.islink(path):
        drop_mount_file(fid)
        raise Fail("folder.missing")
    if os.path.ismount(path) or not hide_device_ok(path):
        raise Fail("lock.failed")
    write_auth(fid, f)
    ensure_dir(store)
    try:
        os.rename(path, os.path.join(store, "data"))
    except OSError:
        remove_empty_dir(store)
        raise Fail("lock.failed")
    shut(store)
    hide_settle(fid, f)
    clean_thumbnails(path)
    clean_recent(path)
    drop_mount_file(fid)
    return True


def hide_reveal(fid, f):
    """Devuelve la carpeta a su ruta. Lo soltado en la carpeta vacía entra en «rescued …»."""
    path, store = f["path"], hide_store(fid, f)
    if not hide_locked(store):
        raise Fail("folder.missing" if not os.path.isdir(path) else "lock.failed")
    if not os.path.isdir(os.path.dirname(path)):
        raise Fail("path.parentMissing")
    strays = None
    if os.path.lexists(path):
        if os.path.islink(path) or not os.path.isdir(path):
            raise Fail("path.notEmpty")
        if os.listdir(path):
            strays = set_strays_aside(fid, path)
        os.rmdir(path)
    try:
        os.chmod(store, 0o700)
        os.rename(os.path.join(store, "data"), path)
    except OSError:
        shut(store)
        hide_settle(fid, f)
        if strays:
            if not os.path.isdir(path):
                os.mkdir(path, 0o700)
            move_children(strays, path)
        raise Fail("mount.failed")
    remove_empty_dir(store)
    return bring_strays(fid, path)


def hide_missing(fid, f):
    """¿Por qué no está? Disco sin conectar o carpeta que ya no existe."""
    parent_disk = [r for r in media_roots() if f["path"].startswith(r + "/")]
    return "disk.missing" if parent_disk and not disk_root(os.path.dirname(f["path"])) else "folder.missing"


def hide_unlock(fid, f, key):
    if not key_ok(f.get("auth") or {}, key):
        raise Fail("key.wrong")
    already = hide_open(fid, f)
    rescued = 0
    if not already:
        if not hide_locked(hide_store(fid, f)):
            raise Fail(hide_missing(fid, f))
        rescued = hide_reveal(fid, f)
    else:
        rescued = bring_strays(fid, f["path"])
    # La necesita el vigía (bloquea si muere el shell) y `holders`.
    write_atomic(mount_file(fid), json.dumps({"id": fid, "type": "hide", "mountPoint": f["path"],
                                              "mountedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
    return {"id": fid, "path": f["path"], "already": already, "rescued": rescued}


def hide_init(reg, meta, key):
    path = validate_new_path(meta.get("path"), reg, full=True)
    if not os.access(os.path.dirname(path), os.W_OK) or (os.path.isdir(path) and not os.access(path, os.W_OK)):
        raise Fail("disk.readOnly")
    ensure_dir(data_dir())
    if not hide_device_ok(path):
        raise Fail("hide.otherDisk")
    fid = secrets.token_hex(8)
    while fid in reg["folders"] or os.path.lexists(os.path.join(hide_base(path), fid)):
        fid = secrets.token_hex(8)
    disk = disk_root(os.path.dirname(path))
    if disk:
        ensure_dir(os.path.join(disk, DISK_DIR))
    f = dict({"name": str(meta.get("name") or "").strip()[:60] or os.path.basename(path), "path": path, "type": "hide",
              "mode": "visible" if meta.get("mode") == "visible" else "hidden",
              "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "auth": key_hash(key)}, **clean_rules(meta.get("rules")))
    made = False
    if not os.path.isdir(path):
        os.mkdir(path, 0o700)
        made = True
    # Registro ANTES de mover: si se corta, la carpeta sigue entera en su sitio y el siguiente
    # arranque la bloquea.
    reg["folders"][fid] = f
    write_registry(reg)
    try:
        hide_lock(fid, f)
    except BaseException:
        if not hide_locked(hide_store(fid, f)):
            reg = read_registry()
            reg["folders"].pop(fid, None)
            write_registry(reg)
            try:
                os.unlink(hide_store(fid, f) + ".json")
            except OSError:
                pass
            if made:
                remove_empty_dir(path)
        raise
    return {"id": fid, "name": f["name"], "path": path, "recoveryKey": ""}


def drop_hide_meta(fid, f):
    """Ya no es nuestra: fuera la huella y, si no queda nada, la carpeta del disco."""
    store = hide_store(fid, f)
    try:
        os.unlink(store + ".json")
    except OSError:
        pass
    base = os.path.dirname(store)
    if base != os.path.join(data_dir(), "locked"):
        drop_disk_dir(os.path.join(os.path.dirname(base), "vaults", "x"))


# ------------------------------------------------------------------ editar y clave
def cmd_update(args):
    fid = args[0] if args else ""
    get_folder(fid)
    try:
        meta = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        raise Fail("update.failed")
    reg = read_registry()
    folder = reg["folders"][fid]
    name = str(meta.get("name") or "").strip()[:60]
    if name:
        folder["name"] = name
    if "rules" in meta:
        folder.update(clean_rules(meta.get("rules")))
    if meta.get("mode") in ("hidden", "visible"):
        folder["mode"] = meta["mode"]
    write_registry(reg)
    # Bloqueada: el modo nuevo se aplica ya; abierta, al bloquearla (finish_lock).
    if is_hide(folder):
        if hide_locked(hide_store(fid, folder)):
            hide_settle(fid, folder)
    elif not is_open(fid, folder):
        if folder["mode"] == "hidden" and os.path.isdir(folder["path"]) and os.listdir(folder["path"]):
            pass  # dejaron algo dentro: no se toca; al abrirla entra en la carpeta cifrada
        else:
            settle_locked_path(fid, folder["path"])
    return {"id": fid, "name": folder["name"], "mode": folder["mode"]}


def cmd_holders(args):
    """Programas que usan la carpeta abierta (fd o cwd dentro), como holders.rs de Omavault."""
    fid = args[0] if args else ""
    if not ID_RE.match(fid):
        raise Fail("folder.unknown")
    info = read_mount(fid) or {}
    if info.get("type") != "hide" and not mount_alive(info):
        return {"id": fid, "apps": []}
    root = info["mountPoint"].rstrip("/")
    me, daemon = os.getpid(), info.get("pid")
    apps = set()
    for name in os.listdir("/proc"):
        if not name.isdigit() or int(name) in (me, daemon):
            continue
        base = "/proc/" + name
        targets = []
        try:
            targets.append(os.readlink(base + "/cwd"))
        except OSError:
            pass
        try:
            for fd in os.listdir(base + "/fd"):
                try:
                    targets.append(os.readlink(base + "/fd/" + fd))
                except OSError:
                    pass
        except OSError:
            continue
        if any(t == root or t.startswith(root + "/") for t in targets):
            try:
                with open(base + "/comm", encoding="utf-8") as f:
                    apps.add(f.read().strip())
            except OSError:
                pass
    return {"id": fid, "apps": sorted(apps)}


def drop_disk_dir(vault):
    """Quita del disco `.super-folder-lock/` si ya no le queda ninguna bóveda."""
    base = os.path.dirname(os.path.dirname(vault))
    for n in ("vaults", "locked", "strays"):
        remove_empty_dir(os.path.join(base, n))
    remove_empty_dir(base)


def cmd_orphans(_args):
    reg = read_registry()
    ids = {}  # id -> nombre del disco ("" = el interno); el de la carpeta no se sabe ya
    for label, base in [("", os.path.join(data_dir(), "vaults"))] + [(os.path.basename(r), disk_vaults(r)) for r in mounted_disks()]:
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for d in names:
            v = os.path.join(base, d)
            if ID_RE.match(d) and d not in reg["folders"] and not os.path.islink(v) \
                    and os.path.isfile(os.path.join(v, "gocryptfs.conf")):
                ids.setdefault(d, label)
    for label, root in [("", data_dir())] + [(os.path.basename(r), os.path.join(r, DISK_DIR)) for r in mounted_disks()]:
        base = os.path.join(root, "locked")
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for d in names:
            if ID_RE.match(d) and d not in reg["folders"] and hide_locked(os.path.join(base, d)):
                ids.setdefault(d, label)
    return {"ids": sorted(ids), "disks": ids}


def readd_key_ok(fid, key):
    """¿Abre esta clave esa carpeta? Sin montar ni mover nada."""
    for root in [data_dir()] + [os.path.join(r, DISK_DIR) for r in mounted_disks()]:
        base = os.path.join(root, "locked")
        if hide_locked(os.path.join(base, fid)):
            try:
                with open(os.path.join(base, fid + ".json"), encoding="utf-8") as fh:
                    auth = json.load(fh)["auth"]
            except (OSError, ValueError, KeyError, TypeError):
                raise Fail("readd.failed")
            return key_ok(auth, key)
    conf = os.path.join(vault_dir(fid), "gocryptfs.conf")
    if not os.path.isfile(conf):
        raise Fail("folder.unknown")
    if not shutil.which("gocryptfs-xray"):
        raise Fail("gocryptfs.missing")
    # xray solo descifra la clave maestra con la clave: no hace falta montar.
    x = subprocess.run(["gocryptfs-xray", "-dumpmasterkey", conf], input=(key + "\n").encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return x.returncode == 0


def hide_readd(fid, base, path, meta, reg):
    if hide_base(path) != base:
        raise Fail("hide.otherDisk")     # volver a otro disco sería copiar
    with open(os.path.join(base, fid + ".json"), encoding="utf-8") as fh:
        auth = json.load(fh)["auth"]
    f = dict({"name": str(meta.get("name") or "").strip()[:60] or os.path.basename(path), "path": path, "type": "hide",
              "mode": "visible" if meta.get("mode") == "visible" else "hidden",
              "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "auth": auth}, **clean_rules(meta.get("rules")))
    reg["folders"][fid] = f
    write_registry(reg)
    hide_settle(fid, f)
    return {"id": fid, "name": f["name"]}


def cmd_readd(args):
    """Sin id («any»): la clave dice cuál es. De una carpeta fuera del listado no se sabe el nombre,
    así que pedir que se elija una de varias no serviría de nada."""
    want = args[0] if args else ""
    if want != "any" and not ID_RE.match(want):
        raise Fail("folder.unknown")
    key = sys.stdin.readline().rstrip("\n")
    try:
        meta = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        raise Fail("readd.failed")
    if not key:
        raise Fail("key.empty")
    reg = read_registry()
    if want in reg["folders"]:
        raise Fail("path.taken")
    matches, problems = [], []
    for cand in (cmd_orphans([])["ids"] if want == "any" else [want]):
        try:
            (matches if readd_key_ok(cand, key) else problems).append(cand)
        except Fail as e:        # una ilegible no impide probar las demás
            problems.append(e)
    key = ""
    if not matches:
        bad = [e.key for e in problems if isinstance(e, Fail)]
        # Sin gocryptfs no se pudo probar todo: decir «clave incorrecta» sería falso.
        raise Fail("gocryptfs.missing" if "gocryptfs.missing" in bad else bad[0] if bad and len(bad) == len(problems) else "key.wrong")
    path = validate_new_path(meta.get("path"), reg)
    bases = {}                   # las escondidas, y dónde están guardadas
    for root in [data_dir()] + [os.path.join(r, DISK_DIR) for r in mounted_disks()]:
        for m in matches:
            if hide_locked(os.path.join(root, "locked", m)):
                bases[m] = os.path.join(root, "locked")
    # Varias con la misma clave: la que pueda ir a esa ruta (una escondida no cambia de disco).
    fid = next((m for m in matches if m not in bases or bases[m] == hide_base(path)), matches[0])
    if fid in bases:
        return hide_readd(fid, bases[fid], path, meta, reg)
    name = str(meta.get("name") or "").strip()[:60] or os.path.basename(path)
    mode = "visible" if meta.get("mode") == "visible" else "hidden"
    if mode == "visible":
        if not os.path.lexists(path):
            os.mkdir(path, 0o700)
    elif os.path.isdir(path) and not os.path.islink(path):
        os.rmdir(path)
    vault = vault_dir(fid)
    reg["folders"][fid] = dict({"name": name, "path": path, "mode": mode,
                                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, **clean_rules(meta.get("rules")))
    if vault != default_vault(fid):
        reg["folders"][fid]["vault"] = vault
    write_registry(reg)
    return {"id": fid, "name": name}


def cmd_forget(args):
    """Solo para una entrada cuyos archivos ya no existen: una carpeta con contenido nunca sale de
    la lista quedándose bloqueada (para eso está `unprotect`, que la devuelve)."""
    fid = args[0] if args else ""
    f = get_folder(fid)
    if is_open(fid, f):
        raise Fail("folder.isOpen")
    if is_hide(f):
        why = "" if hide_locked(hide_store(fid, f)) else hide_missing(fid, f)
    else:
        try:
            require_vault(fid)
            why = ""
        except Fail as e:
            why = e.key
    if why not in ("folder.missing", "vault.missing"):
        raise Fail(why or "forget.exists")
    reg = read_registry()
    del reg["folders"][fid]
    write_registry(reg)
    # visible: la carpeta vacía en su sitio ya no sirve de nada
    if f.get("mode") == "visible":
        remove_empty_dir(f["path"])
    return {"id": fid}


def cmd_destroy(args):
    fid = args[0] if args else ""
    if not ID_RE.match(fid):
        raise Fail("folder.unknown")
    reg = read_registry()
    f = reg["folders"].get(fid)
    if f is not None and is_hide(f):
        raise Fail("destroy.failed")     # el contenido de una escondida no se borra nunca
    if f is None and not os.path.isdir(vault_dir(fid)):
        raise Fail("folder.unknown")
    # Se resuelve ANTES de tocar el registro: después ya no se sabría en qué disco está.
    vault = vault_dir(fid)
    if f is not None and f.get("vault") and not os.path.isdir(vault):
        raise Fail("disk.missing")
    if read_mount(fid):
        cmd_lock([fid])
    if f is not None:
        del reg["folders"][fid]
        write_registry(reg)
        remove_empty_dir(f.get("path", ""))
    shutil.rmtree(vault, ignore_errors=True)
    if os.path.exists(vault):
        raise Fail("destroy.failed")
    if vault != default_vault(fid):
        drop_disk_dir(vault)
    return {"id": fid}


def cmd_info(args):
    fid = args[0] if args else ""
    f = get_folder(fid)
    out = {"id": fid, "name": f.get("name", ""), "mode": f.get("mode", "hidden"), "type": f.get("type", "encrypt")}
    out.update({k: f.get(k) for k in RULE_KEYS + ("idleSeconds", "maxOpenSeconds")})  # reglas, nunca la ruta
    return out


def cmd_passwd(args):
    fid = args[0] if args else ""
    f = get_folder(fid)
    old = sys.stdin.readline().rstrip("\n")
    new = sys.stdin.readline().rstrip("\n")
    if not old:
        raise Fail("key.empty")
    if len(new) < MIN_KEY:
        raise Fail("key.short")
    if is_hide(f):
        if not key_ok(f.get("auth") or {}, old):
            raise Fail("key.wrong")
        reg = read_registry()
        reg["folders"][fid]["auth"] = key_hash(new)
        write_registry(reg)
        if os.path.isdir(hide_base(f["path"])):
            write_auth(fid, reg["folders"][fid])
        return {"id": fid}
    if not shutil.which("gocryptfs"):
        raise Fail("gocryptfs.missing")
    # Orden verificado (2026-11-23): actual, nueva, nueva otra vez. 12 = actual incorrecta.
    p = subprocess.run(["gocryptfs", "-passwd", "-q", require_vault(fid)],
                       input=("%s\n%s\n%s\n" % (old, new, new)).encode("utf-8"),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    old = new = ""
    if p.returncode == 12:
        raise Fail("key.wrong")
    if p.returncode != 0:
        raise Fail("passwd.failed")
    return {"id": fid}


# ------------------------------------------------------------------ subcomandos
def cmd_list(_args):
    reg = read_registry()
    folders = [dict({n: x for n, x in v.items() if n != "auth"}, id=k) for k, v in reg["folders"].items()]
    folders.sort(key=lambda f: (f.get("name") or "").lower())
    return {"folders": folders}


def cmd_status(_args):
    opened = []
    try:
        names = os.listdir(run_dir())
    except FileNotFoundError:
        names = []
    for name in names:
        m = re.match(r"^mount-([0-9a-f]{16})\.json$", name)
        if not m:
            continue
        info = read_mount(m.group(1)) or {}
        if info.get("type") == "hide":
            continue                     # las escondidas se miran en el registro, abajo
        if mount_alive(info):
            opened.append(m.group(1))
        else:
            finish_lock(m.group(1), info)  # resto de un daemon muerto o reciclado
    try:
        ids = {d for d in os.listdir(os.path.join(data_dir(), "vaults")) if ID_RE.match(d)}
    except FileNotFoundError:
        ids = set()
    try:
        folders = read_registry()["folders"]
        ids |= set(folders)              # las de discos externos y las escondidas (solo se cuentan)
        opened += [k for k, v in folders.items() if is_hide(v) and hide_open(k, v)]
    except Fail:
        pass
    return {"open": sorted(opened), "total": len(ids)}


# ------------------------------------------------------------------ quitar protección
def unprotect_lock(fid):
    """Cerrojo mientras se sacan los archivos (dentro, el id). None si otro lo tiene."""
    ensure_dir(run_dir())
    fd = os.open(os.path.join(run_dir(), "unprotect.lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.pwrite(fd, fid.encode(), 0)
    return fd


def unprotecting():
    """Id de la carpeta que se está sacando AHORA, o ""."""
    try:
        fd = os.open(os.path.join(run_dir(), "unprotect.lock"), os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return ""
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return ""
        except OSError:
            return os.pread(fd, 16, 0).decode("ascii", "replace")
    finally:
        os.close(fd)


def staging_dir(fid, path):
    return os.path.join(os.path.dirname(path), ".%s.sfl-%s" % (os.path.basename(path), fid))


def unprotect_mount(fid):
    return os.path.join(run_dir(), "unprotect-%s" % fid)


def clean_unprotect_leftovers():
    """Restos de un `unprotect` que murió a medias: montaje temporal y copia parcial EN CLARO.
    Solo si nadie lo está haciendo ahora, y solo con la bóveda intacta."""
    fd = unprotect_lock("")
    if fd is None:
        return
    try:
        try:
            names = os.listdir(run_dir())
        except OSError:
            names = []
        for n in names:
            if re.match(r"^unprotect-[0-9a-f]{16}$", n):
                mnt = os.path.join(run_dir(), n)
                unmount_now(mnt)
                remove_empty_dir(mnt)
        try:
            folders = read_registry()["folders"]
        except Fail:
            folders = {}
        for fid, f in folders.items():
            st = staging_dir(fid, f.get("path") or "/")
            if ID_RE.match(fid) and os.path.isdir(st) and not os.path.islink(st) \
                    and os.path.isfile(os.path.join(vault_dir(fid), "gocryptfs.conf")):
                shutil.rmtree(st, ignore_errors=True)
    finally:
        os.close(fd)


def tree(root):
    """{ruta relativa: huella} de un árbol; sin el testigo de la raíz."""
    out = {}

    def fail(e):
        raise e
    for base, dirs, files in os.walk(root, onerror=fail):
        for n in dirs + files:
            full = os.path.join(base, n)
            rel = os.path.relpath(full, root)
            if rel == CHECK_NAME:
                continue
            if os.path.islink(full):
                out[rel] = ("link", os.readlink(full))
            elif os.path.isdir(full):
                out[rel] = ("dir",)
            else:
                h = hashlib.sha256()
                with open(full, "rb") as f:
                    for block in iter(lambda: f.read(1 << 20), b""):
                        h.update(block)
                out[rel] = ("file", os.path.getsize(full), h.hexdigest())
    return out


def cmd_unprotect(args):
    fid = args[0] if args else ""
    f = get_folder(fid)
    if is_hide(f):
        # Nada que copiar: vuelve a su sitio y deja de estar en la lista.
        key = sys.stdin.readline().rstrip("\n")
        if not key:
            raise Fail("key.empty")
        r = hide_unlock(fid, f, key)
        reg = read_registry()
        reg["folders"].pop(fid, None)
        write_registry(reg)
        drop_hide_meta(fid, f)
        drop_mount_file(fid)
        return {"id": fid, "path": r["path"], "files": -1}
    if not shutil.which("gocryptfs"):
        raise Fail("gocryptfs.missing")
    info = read_mount(fid)
    if info and mount_alive(info):
        raise Fail("folder.isOpen")
    key = sys.stdin.readline().rstrip("\n")
    if not key:
        raise Fail("key.empty")
    vault = require_vault(fid)
    path = f["path"]
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise Fail("path.parentMissing")
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isdir(path) or os.listdir(path)):
        raise Fail("unprotect.notEmpty")
    lock = unprotect_lock(fid)
    if lock is None:
        raise Fail("folder.unprotecting")

    def stop(_sig, _frame):
        raise Fail("unprotect.failed")
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stop)
    mnt, staging = unprotect_mount(fid), staging_dir(fid, path)
    try:
        unmount_now(mnt)
        ensure_dir(mnt)
        if os.path.lexists(staging):  # copia parcial de un intento que murió: la bóveda sigue
            if os.path.islink(staging) or not os.path.isdir(staging):
                raise Fail("unprotect.notEmpty")
            shutil.rmtree(staging)
        p = subprocess.Popen(["gocryptfs", "-q", "-ro", "-passfile", "/dev/stdin", vault, mnt],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate((key + "\n").encode("utf-8"))
        key = ""
        if p.returncode != 0 or mnt not in mounted_points():
            raise Fail("key.wrong" if p.returncode == 12 else "mount.failed")
        need = sum(os.lstat(os.path.join(b, n)).st_size for b, _d, fs in os.walk(mnt) for n in fs)
        st = os.statvfs(parent)
        if st.f_bavail * st.f_frsize < need + (64 << 20):
            raise Fail("unprotect.space")
        shutil.copytree(mnt, staging, symlinks=True)
        try:
            os.unlink(os.path.join(staging, CHECK_NAME))
        except FileNotFoundError:
            pass
        os.sync()
        # Lo que garantiza que no se pierde nada: los dos árboles, byte a byte.
        before = tree(mnt)
        if before != tree(staging):
            raise Fail("unprotect.failed")
        if os.path.isdir(path):
            os.rmdir(path)  # vacía (modo visible); si ya no lo está, falla y no se toca nada
        os.rename(staging, path)
    except Fail:
        raise
    except (OSError, shutil.Error):
        raise Fail("unprotect.failed")
    finally:
        key = ""
        unmount_now(mnt)
        remove_empty_dir(mnt)
        if os.path.isdir(staging) and not os.path.islink(staging):
            shutil.rmtree(staging, ignore_errors=True)
        if f.get("mode") == "visible" and not os.path.lexists(path):
            os.mkdir(path, 0o700)  # falló entre medias: la carpeta visible vuelve a su sitio
    # Ya está fuera y comprobado: registro primero (si algo falla aquí, la bóveda queda «sin
    # registrar», nunca al revés) y la bóveda al final.
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)
    os.sync()
    reg = read_registry()
    reg["folders"].pop(fid, None)
    write_registry(reg)
    shutil.rmtree(vault, ignore_errors=True)
    if vault != default_vault(fid):
        drop_disk_dir(vault)
    os.close(lock)
    return {"id": fid, "path": path, "files": sum(1 for v in before.values() if v[0] != "dir")}


def cmd_check(_args):
    try:
        path = json.loads(sys.stdin.readline() or "{}").get("path")
    except (ValueError, AttributeError):
        raise Fail("path.invalid")
    path = validate_new_path(path, read_registry(), full=True)
    state = "new" if not os.path.isdir(path) else "full" if os.listdir(path) else "empty"
    return {"state": state, "canHide": hide_device_ok(path)}


def cmd_unlock(args):
    fid = args[0] if args else ""
    if fid and unprotecting() == fid:
        raise Fail("folder.unprotecting")
    folder = get_folder(fid)
    if is_hide(folder):
        key = sys.stdin.readline().rstrip("\n")
        if not key:
            raise Fail("key.empty")
        return hide_unlock(fid, folder, key)
    if not shutil.which("gocryptfs"):
        raise Fail("gocryptfs.missing")
    path = folder["path"]
    info = read_mount(fid)
    if info and mount_alive(info):
        return {"id": fid, "path": path, "already": True}
    key = sys.stdin.readline().rstrip("\n")
    if not key:
        raise Fail("key.empty")
    require_vault(fid)
    if not os.path.isdir(os.path.dirname(path)):
        raise Fail("path.parentMissing")
    created = False
    strays = None
    if os.path.lexists(path):
        if not os.path.isdir(path) or os.path.islink(path):
            raise Fail("path.notEmpty")
        if os.listdir(path):
            # Visible (o alguien la creó): lo que se soltó en la carpeta vacía mientras estaba
            # bloqueada se aparta, se monta, y entra DENTRO de la carpeta cifrada (B2, M1.T7.S4).
            strays = set_strays_aside(fid, path)
    else:
        os.mkdir(path, 0o700)
        created = True
    recovery = len(args) > 1 and args[1] == "recovery"
    if recovery:
        # La de recuperación se escribe con o sin guiones/espacios: solo cuentan los 64 hex.
        key = re.sub(r"[^0-9a-fA-F]", "", key).lower()
        if len(key) != 64:
            if created:
                remove_empty_dir(path)
            if strays:
                move_children(strays, path)
            raise Fail("recovery.invalid")
    cmd = ["gocryptfs", "-q", "-masterkey=stdin", vault_dir(fid), path] if recovery else \
        ["gocryptfs", "-q", "-passfile", "/dev/stdin", vault_dir(fid), path]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proc.communicate((key + "\n").encode("utf-8"))
    key = ""
    if proc.returncode != 0:
        if created:
            remove_empty_dir(path)
        if strays:
            move_children(strays, path)  # todo vuelve a su sitio
        raise Fail("key.wrong" if proc.returncode == 12 else "mount.failed")
    pid = find_daemon(path)
    if pid is None:
        subprocess.run(["fusermount3", "-u", "-z", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created:
            remove_empty_dir(path)
        if strays:
            move_children(strays, path)
        raise Fail("mount.failed")
    if recovery:
        verdict = recovery_verdict(fid, path)
        if verdict != "ok":
            unmount_now(path)
            if created:
                remove_empty_dir(path)
            if strays:
                move_children(strays, path)
            raise Fail("key.wrong" if verdict == "wrong" else "recovery.unverifiable")
    try:
        write_check(path)
    except OSError:
        pass
    rescued = bring_strays(fid, path)
    write_atomic(mount_file(fid), json.dumps({
        "id": fid,
        "pid": pid,
        "pidStartTime": pid_start_time(pid),
        "mountPoint": path,
        "mountedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }) + "\n")
    return {"id": fid, "path": path, "already": False, "rescued": rescued}


def set_strays_aside(fid, path):
    """Mueve lo que haya en `path` a una carpeta 700 dentro de la de datos (nunca se borra)."""
    disk = disk_root(os.path.dirname(path))  # no de `path`: abierta y cifrada, ella misma es un montaje
    home = os.path.join(disk, DISK_DIR) if disk else data_dir()
    aside = os.path.join(home, "strays", "%s-%s-%s" % (fid, time.strftime("%Y%m%d%H%M%S"), secrets.token_hex(3)))
    os.makedirs(aside, mode=0o700)
    os.chmod(os.path.dirname(aside), 0o700)
    move_children(path, aside)
    return aside


def bring_strays(fid, path):
    """Mete en la carpeta ya abierta TODO lo apartado de ella, también de un intento que murió."""
    disk = disk_root(os.path.dirname(path))  # no de `path`: abierta y cifrada, ella misma es un montaje
    base = os.path.join(os.path.join(disk, DISK_DIR) if disk else data_dir(), "strays")
    try:
        names = sorted(n for n in os.listdir(base) if n.startswith(fid + "-"))
    except OSError:
        return 0
    total = 0
    for n in names:
        src = os.path.join(base, n)
        if not os.path.isdir(src) or os.path.islink(src):
            continue
        if not os.listdir(src):
            remove_empty_dir(src)
            continue
        dest = os.path.join(path, "rescued " + time.strftime("%Y-%m-%d %H%M%S"))
        os.makedirs(dest, mode=0o700, exist_ok=True)
        total += move_children(src, dest)
    remove_empty_dir(base)
    return total


def move_children(src, dst):
    """Mueve el contenido de src a dst (entre sistemas de archivos: copia + borrado) y quita src."""
    n = 0
    for name in os.listdir(src):
        target = os.path.join(dst, name)
        if os.path.lexists(target):
            target = os.path.join(dst, "%s (%d)" % (name, int(time.time())))
        shutil.move(os.path.join(src, name), target)
        n += 1
    if os.path.basename(os.path.dirname(src)) == "strays":
        remove_empty_dir(src)
    return n


def folder_mode(fid):
    try:
        return get_folder(fid).get("mode", "hidden")
    except Fail:
        return "hidden"


def settle_locked_path(fid, path):
    """Bloqueada: oculta = la ruta no existe; visible = carpeta vacía en su sitio."""
    if folder_mode(fid) == "visible":
        if not os.path.lexists(path) and os.path.isdir(os.path.dirname(path)):
            os.mkdir(path, 0o700)
    else:
        remove_empty_dir(path)


def finish_lock(fid, info):
    """Desmonta si sigue montado, quita la carpeta vacía (modo oculto) y el mount-<id>.json."""
    if info.get("type") == "hide":
        return None                      # nada montado: lo suyo es hide_lock
    path = info.get("mountPoint")
    if not path:
        try:
            path = get_folder(fid)["path"]
        except Fail:
            path = None
    if path and path in mounted_points():
        subprocess.run(["fusermount3", "-u", "-z", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if path and path not in mounted_points():
        settle_locked_path(fid, path)
        clean_thumbnails(path)
        clean_recent(path)
    try:
        os.unlink(mount_file(fid))
    except FileNotFoundError:
        pass
    return path


def cmd_lock(args):
    fid = args[0] if args else ""
    if not ID_RE.match(fid):
        raise Fail("folder.unknown")
    try:
        f = get_folder(fid)
    except Fail:
        f = {}
    if is_hide(f):
        return {"id": fid, "wasOpen": hide_lock(fid, f)}
    info = read_mount(fid) or {}
    was_open = False
    pid = info.get("pid")
    if isinstance(pid, int) and pid_start_time(pid) == info.get("pidStartTime"):
        was_open = True
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(60):  # hasta 3 s: gocryptfs desmonta (o diferido si está ocupado) y sale
            if pid_start_time(pid) != info.get("pidStartTime"):
                break
            time.sleep(0.05)
    path = finish_lock(fid, info)
    if path and path in mounted_points():
        raise Fail("lock.failed")
    return {"id": fid, "wasOpen": was_open}


def drop_old_temps():
    """Temporales de una escritura que murió a medias (más de una hora)."""
    for base in (data_dir(), os.path.join(data_dir(), "locked"), run_dir()):
        try:
            names = [n for n in os.listdir(base) if n.startswith(".tmp-")]
        except OSError:
            continue
        for n in names:
            full = os.path.join(base, n)
            try:
                if time.time() - os.lstat(full).st_mtime > 3600:
                    os.unlink(full)
            except OSError:
                pass


def cmd_lockall(_args):
    locked, failed = [], []
    drop_old_temps()
    clean_unprotect_leftovers()
    # Escondidas abiertas: por el registro, no por run_dir (tras reiniciar el equipo no hay).
    try:
        hides = {k: v for k, v in read_registry()["folders"].items() if is_hide(v)}
    except Fail:
        hides = {}
    for fid, f in hides.items():
        try:
            if hide_lock(fid, f):
                locked.append(fid)
        except Fail as e:
            if e.key != "folder.missing":    # disco sin conectar: no hay nada que bloquear
                failed.append(fid)
        except OSError:
            failed.append(fid)
    try:
        names = os.listdir(run_dir())
    except FileNotFoundError:
        names = []
    for name in names:
        m = re.match(r"^mount-([0-9a-f]{16})\.json$", name)
        if not m:
            continue
        if m.group(1) in hides:
            continue
        try:
            cmd_lock([m.group(1)])
            locked.append(m.group(1))
        except Fail:
            failed.append(m.group(1))
    if failed:
        raise Fail("lock.failed")
    return {"locked": locked}


COMMANDS = {
    "list": cmd_list,
    "status": cmd_status,
    "unlock": cmd_unlock,
    "lock": cmd_lock,
    "lockall": cmd_lockall,
    "init": cmd_init,
    "update": cmd_update,
    "passwd": cmd_passwd,
    "info": cmd_info,
    "holders": cmd_holders,
    "check": cmd_check,
    "unprotect": cmd_unprotect,
    "orphans": cmd_orphans,
    "readd": cmd_readd,
    "forget": cmd_forget,
    "destroy": cmd_destroy,
}


def main(argv):
    cmd = COMMANDS.get(argv[1] if len(argv) > 1 else "")
    if cmd is None:
        print(json.dumps({"ok": False, "error": "command.unknown", "data": None}))
        return 2
    try:
        harden()
        data = cmd(argv[2:])
    except Fail as e:
        print(json.dumps({"ok": False, "error": e.key, "data": None}))
        return 1
    except Exception:  # nunca volcar trazas: podrían llevar rutas
        print(json.dumps({"ok": False, "error": "internal", "data": None}))
        return 1
    print(json.dumps({"ok": True, "error": None, "data": data}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
