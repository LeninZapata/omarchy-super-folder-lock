"""Pruebas del auxiliar bin/folderlock.py en un $HOME de pruebas (nunca el real).

Cada prueba crea su sandbox en /tmp/sfl-sandbox.*, una bóveda con clave conocida
(`gocryptfs -init`) y su entrada en el registro, y lo destruye al acabar.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "bin", "folderlock.py")
KEY = "test-key-123"
FID = "0123456789abcdef"


class Sandbox:
    def __init__(self):
        self.base = tempfile.mkdtemp(prefix="sfl-sandbox.", dir="/tmp")
        self.home = os.path.join(self.base, "home")
        self.run = os.path.join(self.base, "run")
        os.makedirs(self.home, mode=0o700)
        os.makedirs(self.run, mode=0o700)
        # Todas las XDG_* dentro del sandbox: la sesión de Lenin define XDG_CACHE_HOME y
        # XDG_DATA_HOME, y sin esto el auxiliar miraría sus miniaturas y recientes reales.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        self.env.update(HOME=self.home, XDG_RUNTIME_DIR=self.run,
                        XDG_CACHE_HOME=os.path.join(self.home, ".cache"),
                        XDG_DATA_HOME=os.path.join(self.home, ".local", "share"),
                        XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        XDG_STATE_HOME=os.path.join(self.home, ".local", "state"))
        self.data = os.path.join(self.home, ".local", "share", "omarchy", "super-folder-lock")

    def helper(self, *args, stdin=""):
        p = subprocess.run(["python3", "-I", HELPER] + list(args), input=stdin, capture_output=True,
                           text=True, env=self.env, timeout=30)
        lines = p.stdout.strip().splitlines()
        assert len(lines) == 1, p.stdout + p.stderr
        return json.loads(lines[0])

    def add_folder(self, fid=FID, rel="sfl-test-a1", key=KEY):
        """Bóveda + registro a mano (crear desde la ventana llega en A3)."""
        vault = os.path.join(self.data, "vaults", fid)
        os.makedirs(vault, mode=0o700)
        subprocess.run(["gocryptfs", "-init", "-q", "-passfile", "/dev/stdin", vault], input=key + "\n",
                       text=True, check=True, capture_output=True)
        path = os.path.join(self.home, rel)
        reg_path = os.path.join(self.data, "folders.sfldb")
        reg = {"schemaVersion": 1, "folders": {}}
        if os.path.exists(reg_path):
            with open(reg_path) as f:
                reg = json.loads(f.read().partition("\n")[2])
        reg["folders"][fid] = {"name": rel, "path": path, "mode": "hidden", "createdAt": "2026-11-23T17:00:00"}
        with open(reg_path, "w") as f:
            f.write("SFLDB 1 — do not edit; managed by Super Folder Lock\n" + json.dumps(reg))
        return path

    def mounted(self, path):
        with open("/proc/mounts") as f:
            return any(line.split()[1] == path for line in f)

    def clean(self):
        with open("/proc/mounts") as f:
            points = [line.split()[1] for line in f if line.split()[1].startswith(self.base + "/")]
        for p in points:
            subprocess.run(["fusermount3", "-u", "-z", p], capture_output=True)
        subprocess.run(["chmod", "-R", "u+rwx", self.base], capture_output=True)   # almacenes en 000
        shutil.rmtree(self.base, ignore_errors=True)


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.clean)

    def test_list_empty_and_broken_registry(self):
        r = self.sb.helper("list")
        self.assertEqual(r, {"ok": True, "error": None, "data": {"folders": []}})
        os.makedirs(self.sb.data, exist_ok=True)
        with open(os.path.join(self.sb.data, "folders.sfldb"), "w") as f:
            f.write("not a registry")
        r = self.sb.helper("list")
        self.assertEqual(r["error"], "registry.broken")
        with open(os.path.join(self.sb.data, "folders.sfldb")) as f:
            self.assertEqual(f.read(), "not a registry")  # roto: no se pisa

    def test_wrong_key_leaves_nothing(self):
        path = self.sb.add_folder()
        r = self.sb.helper("unlock", FID, stdin="mala\n")
        self.assertEqual(r["error"], "key.wrong")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.sb.helper("status")["data"], {"open": [], "total": 1})

    def test_unlock_lock_cycle(self):
        path = self.sb.add_folder()
        r = self.sb.helper("unlock", FID, stdin=KEY + "\n")
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.sb.mounted(path))
        with open(os.path.join(path, "foto1.txt"), "w") as f:
            f.write("hola")
        with open(os.path.join(self.sb.run, "super-folder-lock", "mount-%s.json" % FID)) as f:
            info = json.load(f)
        self.assertEqual(info["mountPoint"], path)
        self.assertEqual(oct(os.stat(os.path.join(self.sb.run, "super-folder-lock")).st_mode & 0o777), "0o700")
        self.assertEqual(self.sb.helper("status")["data"]["open"], [FID])
        # la clave nunca sale en la salida
        self.assertNotIn(KEY, json.dumps(r))
        r = self.sb.helper("lock", FID)
        self.assertEqual(r["data"], {"id": FID, "wasOpen": True})
        self.assertFalse(self.sb.mounted(path))
        self.assertFalse(os.path.exists(path))  # modo oculto: la ruta desaparece
        self.assertEqual(subprocess.run(["pgrep", "-f", "gocryptfs.*" + path], capture_output=True).returncode, 1)
        self.assertEqual(self.sb.helper("status")["data"]["open"], [])
        # y vuelve a abrir con lo que había dentro
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        with open(os.path.join(path, "foto1.txt")) as f:
            self.assertEqual(f.read(), "hola")
        self.assertTrue(self.sb.helper("lockall")["ok"])
        self.assertFalse(os.path.exists(path))

    def test_lock_while_in_use_cuts_access(self):
        """Bloqueo fuerte: con un archivo abierto dentro, la foto siguiente ya no carga.

        Límite conocido (PLAN.md §3): lo que el kernel ya tiene en caché de un archivo ABIERTO
        antes del bloqueo aún se relee; cerrarlo o abrir cualquier otro falla. gocryptfs no
        ofrece direct_io, así que no se puede evitar desde fuera, igual que lo que la app ya
        cargó en memoria."""
        path = self.sb.add_folder()
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        for n in (1, 2):
            with open(os.path.join(path, "foto%d.txt" % n), "w") as f:
                f.write("foto %d" % n)
        reader = subprocess.Popen(
            ["python3", "-I", "-c",
             "import sys,time,os\n"
             "f=open(sys.argv[1]); print(f.read(), flush=True)\n"
             "sys.stdin.readline()\n"
             "try:\n f.seek(0); f.read(); print('read-ok', flush=True)\n"
             "except OSError as e: print('read-fail', e.errno, flush=True)\n"
             "try:\n open(sys.argv[2]).read(); print('next-ok', flush=True)\n"
             "except OSError as e: print('next-fail', e.errno, flush=True)\n"
             "try:\n f.close()\n"
             "except OSError: pass\n",
             os.path.join(path, "foto1.txt"), os.path.join(path, "foto2.txt")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.assertEqual(reader.stdout.readline().strip(), "foto 1")
        r = self.sb.helper("lock", FID)
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.sb.mounted(path))
        out, _ = reader.communicate("\n", timeout=10)
        self.assertIn("next-fail", out)   # «la foto siguiente» no se encuentra
        # y el archivo ya abierto: o falla, o sale de la caché del kernel (límite conocido)
        self.assertTrue("read-fail" in out or "read-ok" in out)
        self.assertFalse(os.path.exists(path))

    def test_lock_cleans_thumbnails_and_recent(self):
        import struct, zlib, urllib.parse
        path = self.sb.add_folder()
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])

        def png(uri):
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                    + chunk(b"tEXt", b"Thumb::URI\0" + uri.encode()) + chunk(b"IEND", b""))
        thumbs = os.path.join(self.sb.home, ".cache", "thumbnails", "large")
        os.makedirs(thumbs)
        inside = "file://" + urllib.parse.quote(os.path.join(path, "mi foto.png"))
        outside = "file://" + urllib.parse.quote(os.path.join(self.sb.home, "otra.png"))
        with open(os.path.join(thumbs, "a.png"), "wb") as f:
            f.write(png(inside))
        with open(os.path.join(thumbs, "b.png"), "wb") as f:
            f.write(png(outside))
        xbel = os.path.join(self.sb.home, ".local", "share", "recently-used.xbel")
        with open(xbel, "w") as f:
            f.write('<?xml version="1.0"?>\n<xbel version="1.0">\n'
                    '  <bookmark href="%s" added="x">\n    <info/>\n  </bookmark>\n'
                    '  <bookmark href="%s" added="y">\n    <info/>\n  </bookmark>\n</xbel>\n' % (inside, outside))
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        self.assertEqual(sorted(os.listdir(thumbs)), ["b.png"])
        with open(xbel) as f:
            text = f.read()
        self.assertNotIn("mi%20foto", text)
        self.assertIn("otra.png", text)
        self.assertTrue(text.rstrip().endswith("</xbel>"))

    def init(self, rel, key=KEY, name="", rules=None, absolute=None):
        meta = {"path": absolute or os.path.join(self.sb.home, rel), "name": name, "rules": rules or {}}
        return self.sb.helper("init", stdin=key + "\n" + json.dumps(meta) + "\n")

    def test_init_creates_hidden_folder_and_recovery_key(self):
        os.makedirs(os.path.join(self.sb.home, "Fotos"))
        r = self.init("Fotos/Viaje", rules={"idleLock": "on", "idleSeconds": 120, "bogus": 1, "workspaceLock": "maybe"})
        self.assertTrue(r["ok"], r)
        fid, path = r["data"]["id"], r["data"]["path"]
        self.assertRegex(r["data"]["recoveryKey"], r"^([0-9a-f]{8}-){7}[0-9a-f]{8}$")
        self.assertEqual(r["data"]["name"], "Viaje")
        self.assertFalse(os.path.exists(path))  # oculta: bloqueada no existe
        folder = self.sb.helper("list")["data"]["folders"][0]
        self.assertEqual((folder["idleLock"], folder["idleSeconds"], folder["workspaceLock"]), ("on", 120, "inherit"))
        self.assertNotIn("bogus", folder)
        self.assertNotIn(KEY, json.dumps(r))
        # permisos: carpeta de datos 700, registro 600
        self.assertEqual(os.stat(self.sb.data).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.sb.data, "folders.sfldb")).st_mode & 0o777, 0o600)
        # se abre con la clave, y también con la de recuperación (gocryptfs -masterkey)
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        self.assertTrue(self.sb.mounted(path))
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        mnt = os.path.join(self.sb.base, "mk")
        os.mkdir(mnt)
        p = subprocess.run(["gocryptfs", "-q", "-masterkey=stdin", os.path.join(self.sb.data, "vaults", fid), mnt],
                           input=r["data"]["recoveryKey"] + "\n", text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        subprocess.run(["fusermount3", "-u", mnt])

    def test_init_rejects_bad_paths(self):
        os.makedirs(os.path.join(self.sb.home, "llena"))
        open(os.path.join(self.sb.home, "llena", "x"), "w").close()
        os.makedirs(os.path.join(self.sb.home, "vacia"))
        os.symlink(self.sb.home, os.path.join(self.sb.home, "enlace"))
        cases = {
            "llena": "path.notEmpty",
            "no/existe/madre": "path.parentMissing",
            "enlace/x": "path.outsideHome",
        }
        for rel, err in cases.items():
            self.assertEqual(self.init(rel)["error"], err, rel)
        self.assertEqual(self.init("", absolute="/tmp/fuera-de-home")["error"], "path.outsideHome")
        self.assertEqual(self.init("", absolute="relativa")["error"], "path.invalid")
        self.assertEqual(self.init("corta", key="1234")["error"], "key.short")
        self.assertTrue(self.init("vacia")["ok"])  # vacía sí vale
        self.assertEqual(self.init("vacia")["error"], "path.taken")
        self.assertEqual(self.init("vacia/dentro", absolute=None)["error"], "path.parentMissing")
        os.makedirs(os.path.join(self.sb.home, "padre", "hija"))
        self.assertTrue(self.init("padre/hija")["ok"])
        self.assertEqual(self.init("padre")["error"], "path.taken")  # contiene una protegida (oculta, ya no se ve)
        self.assertEqual(len(os.listdir(os.path.join(self.sb.data, "vaults"))), 2)  # los fallos no dejan bóveda

    def test_update_and_passwd(self):
        path = self.sb.add_folder()
        r = self.sb.helper("update", FID, stdin=json.dumps({"name": "Viaje", "rules": {"idleLock": "off", "screenLock": "on", "x": 1}}) + "\n")
        self.assertTrue(r["ok"], r)
        f = self.sb.helper("list")["data"]["folders"][0]
        self.assertEqual((f["name"], f["idleLock"], f["screenLock"], f["path"]), ("Viaje", "off", "on", path))
        self.assertNotIn("x", f)
        # cambiar la clave: la actual mal → key.wrong; corta → key.short; bien → la vieja ya no abre
        self.assertEqual(self.sb.helper("passwd", FID, stdin="mala\nnueva-123\n")["error"], "key.wrong")
        self.assertEqual(self.sb.helper("passwd", FID, stdin=KEY + "\n1234\n")["error"], "key.short")
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])          # abierta mientras cambia
        r = self.sb.helper("passwd", FID, stdin=KEY + "\nnueva-123\n")
        self.assertTrue(r["ok"], r)
        self.assertNotIn("nueva-123", json.dumps(r))
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        self.assertEqual(self.sb.helper("unlock", FID, stdin=KEY + "\n")["error"], "key.wrong")
        self.assertTrue(self.sb.helper("unlock", FID, stdin="nueva-123\n")["ok"])

    def test_visible_mode(self):
        meta = {"path": os.path.join(self.sb.home, "Diario"), "name": "Diario", "mode": "visible"}
        r = self.sb.helper("init", stdin=KEY + "\n" + json.dumps(meta) + "\n")
        self.assertTrue(r["ok"], r)
        fid, path = r["data"]["id"], r["data"]["path"]
        self.assertTrue(os.path.isdir(path) and not os.listdir(path))       # visible: vacía en su sitio
        info = self.sb.helper("info", fid)["data"]
        self.assertEqual((info["name"], info["mode"], info["idleLock"]), ("Diario", "visible", "inherit"))
        self.assertNotIn("path", info)
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        with open(os.path.join(path, "secreto.txt"), "w") as f:
            f.write("dentro")
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        self.assertFalse(self.sb.mounted(path))
        self.assertEqual(os.listdir(path), [])                                # bloqueada: vacía, no desaparece
        # alguien suelta un archivo en la carpeta vacía → al abrir entra en la cifrada
        with open(os.path.join(path, "suelto.txt"), "w") as f:
            f.write("suelto")
        r = self.sb.helper("unlock", fid, stdin=KEY + "\n")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["data"]["rescued"], 1)
        names = sorted(os.listdir(path))
        self.assertIn("secreto.txt", names)
        rescued = [n for n in names if n.startswith("rescued ")]
        self.assertEqual(len(rescued), 1)
        with open(os.path.join(path, rescued[0], "suelto.txt")) as f:
            self.assertEqual(f.read(), "suelto")
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        self.assertEqual(os.listdir(path), [])
        # con clave mala, lo suelto vuelve a su sitio
        with open(os.path.join(path, "otro.txt"), "w") as f:
            f.write("x")
        self.assertEqual(self.sb.helper("unlock", fid, stdin="mala\n")["error"], "key.wrong")
        self.assertEqual(os.listdir(path), ["otro.txt"])
        os.unlink(os.path.join(path, "otro.txt"))
        # cambiar de modo bloqueada: se aplica ya
        self.assertTrue(self.sb.helper("update", fid, stdin=json.dumps({"mode": "hidden"}) + "\n")["ok"])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(self.sb.helper("update", fid, stdin=json.dumps({"mode": "visible"}) + "\n")["ok"])
        self.assertTrue(os.path.isdir(path))

    def test_unlock_with_recovery_key(self):
        os.makedirs(os.path.join(self.sb.home, "R"))
        r = self.sb.helper("init", stdin=KEY + "\n" + json.dumps({"path": os.path.join(self.sb.home, "R", "x")}) + "\n")
        fid, rec, path = r["data"]["id"], r["data"]["recoveryKey"], r["data"]["path"]
        self.assertEqual(self.sb.helper("unlock", fid, "recovery", stdin="1234\n")["error"], "recovery.invalid")
        self.assertFalse(os.path.exists(path))
        bad = "0" * 64                   # gocryptfs montaría con esto: el testigo lo impide
        self.assertEqual(self.sb.helper("unlock", fid, "recovery", stdin=bad + "\n")["error"], "key.wrong")
        self.assertFalse(os.path.exists(path))
        self.assertFalse(self.sb.mounted(path))
        # con guiones, espacios y mayúsculas también vale
        r = self.sb.helper("unlock", fid, "recovery", stdin=rec.upper().replace("-", " - ") + "\n")
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.sb.mounted(path))
        self.assertTrue(os.path.exists(os.path.join(path, ".super-folder-lock")))
        self.assertTrue(self.sb.helper("lock", fid)["ok"])

    def test_recovery_on_vault_without_check(self):
        """Carpeta de antes del testigo: vacía → no se puede verificar → se rechaza."""
        path = self.sb.add_folder()                     # creada a mano, sin testigo
        rec = subprocess.run(["gocryptfs-xray", "-dumpmasterkey", os.path.join(self.sb.data, "vaults", FID, "gocryptfs.conf")],
                             input=KEY + "\n", text=True, capture_output=True).stdout.strip().splitlines()[-1]
        self.assertEqual(self.sb.helper("unlock", FID, "recovery", stdin=rec + "\n")["error"], "recovery.unverifiable")
        self.assertFalse(self.sb.mounted(path))
        # al abrirla con su clave normal gana el testigo; desde entonces la recuperación funciona
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        self.assertEqual(self.sb.helper("unlock", FID, "recovery", stdin="f" * 64 + "\n")["error"], "key.wrong")
        self.assertTrue(self.sb.helper("unlock", FID, "recovery", stdin=rec + "\n")["ok"])
        self.assertTrue(self.sb.helper("lock", FID)["ok"])

    def test_holders(self):
        path = self.sb.add_folder()
        self.assertEqual(self.sb.helper("holders", FID)["data"]["apps"], [])      # bloqueada
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        self.assertEqual(self.sb.helper("holders", FID)["data"]["apps"], [])
        with open(os.path.join(path, "a.txt"), "w") as f:
            f.write("x")
        sleeper = subprocess.Popen(["sleep", "30"], cwd=path)                      # cwd dentro
        try:
            with open(os.path.join(path, "a.txt")):                                # fd dentro (este proceso)
                apps = self.sb.helper("holders", FID)["data"]["apps"]
            self.assertIn("sleep", apps)
            self.assertTrue(any(a.startswith("python") for a in apps), apps)
            self.assertNotIn("a.txt", json.dumps(apps))
        finally:
            sleeper.kill(); sleeper.wait()
        self.assertTrue(self.sb.helper("lock", FID)["ok"])

    def test_orphans_readd_forget_destroy(self):
        path = self.sb.add_folder()
        with open(os.path.join(self.sb.data, "folders.sfldb"), "w") as f:
            f.write("SFLDB 1\n" + json.dumps({"schemaVersion": 1, "folders": {}}))   # registro «perdido»
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [FID])
        meta = {"path": path, "name": "Vuelta", "mode": "visible"}
        self.assertEqual(self.sb.helper("readd", FID, stdin="mala\n" + json.dumps(meta) + "\n")["error"], "key.wrong")
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [FID])
        r = self.sb.helper("readd", FID, stdin=KEY + "\n" + json.dumps(meta) + "\n")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [])
        self.assertTrue(os.path.isdir(path))                                     # visible
        # olvidar: abierta no; bloqueada sí → vuelve a «sin registrar»; la bóveda sigue
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        self.assertEqual(self.sb.helper("forget", FID)["error"], "folder.isOpen")
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        self.assertTrue(self.sb.helper("forget", FID)["ok"])
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [FID])
        self.assertFalse(os.path.exists(path))
        # borrar: también una huérfana; abierta se bloquea antes
        self.assertTrue(self.sb.helper("readd", FID, stdin=KEY + "\n" + json.dumps(meta) + "\n")["ok"])
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        self.assertTrue(self.sb.helper("destroy", FID)["ok"])
        self.assertFalse(self.sb.mounted(path))
        self.assertFalse(os.path.exists(os.path.join(self.sb.data, "vaults", FID)))
        self.assertEqual(self.sb.helper("list")["data"]["folders"], [])
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [])

    def test_external_disk(self):
        """Disco externo (aquí, un montaje FUSE que hace de disco): lo cifrado se queda EN el disco."""
        media = os.path.join(self.sb.base, "media"); disk = os.path.join(media, "Box")
        os.makedirs(disk)
        # El «disco» se simula desde fuera (fusermount3, setuid, no entra en un FUSE ajeno): el
        # mismo auxiliar con media_roots/ismount/mounted_points sustituidos. Desconectar = apartarlo.
        code = ("import os,sys\nsys.path.insert(0,%r)\nimport folderlock as f\nD=%r\nreal=os.path.ismount; pts=f.mounted_points\n"
                "f.media_roots=lambda:[%r]\nos.path.ismount=lambda p: (p==D and os.path.isdir(D)) or real(p)\n"
                "f.mounted_points=lambda: pts()|({D} if os.path.isdir(D) else set())\n"
                "sys.exit(f.main(['x']+sys.argv[1:]))") % (os.path.dirname(os.path.abspath(HELPER)), disk, media)

        def helper(*args, stdin=""):
            out = subprocess.run(["python3", "-I", "-c", code] + list(args), input=stdin, capture_output=True, text=True,
                                 env=self.sb.env, timeout=30)
            self.assertEqual(len(out.stdout.strip().splitlines()), 1, out.stdout + out.stderr)
            return json.loads(out.stdout)
        self.sb.helper = helper
        hidden = os.path.join(disk, ".super-folder-lock")
        os.makedirs(os.path.join(disk, "x"))
        mk = lambda path, **kw: self.sb.helper("init", stdin=KEY + "\n" + json.dumps(dict({"path": path}, **kw)) + "\n")
        # fuera de un disco montado, o el disco mismo: no
        os.makedirs(os.path.join(media, "NoMontado"))
        self.assertEqual(mk(os.path.join(media, "NoMontado", "a"))["error"], "path.outsideHome")
        self.assertEqual(mk(disk)["error"], "path.outsideHome")
        # esconder en el disco: se queda en el disco, y sin él conectado se dice
        os.makedirs(os.path.join(disk, "x", "Mias", "sub"))
        with open(os.path.join(disk, "x", "Mias", "f"), "w") as fh:
            fh.write("hola")
        ino = os.lstat(os.path.join(disk, "x", "Mias", "f")).st_ino
        hid = mk(os.path.join(disk, "x", "Mias"), type="hide")
        self.assertTrue(hid["ok"], hid)
        hid = hid["data"]["id"]
        self.assertEqual(sorted(os.listdir(os.path.join(hidden, "locked"))), [hid, hid + ".json"])
        self.assertFalse(os.path.exists(os.path.join(disk, "x", "Mias")))
        os.rename(disk, disk + ".off")
        self.assertEqual(self.sb.helper("unlock", hid, stdin=KEY + "\n")["error"], "disk.missing")
        self.assertEqual(self.sb.helper("forget", hid)["error"], "disk.missing")
        self.assertTrue(self.sb.helper("lockall")["ok"])
        os.rename(disk + ".off", disk)
        self.assertTrue(self.sb.helper("forget", hid)["ok"])
        self.assertEqual(self.sb.helper("orphans")["data"]["disks"], {hid: "Box"})
        back = lambda p: self.sb.helper("readd", hid, stdin=KEY + "\n" + json.dumps({"path": p}) + "\n")
        self.assertEqual(back(os.path.join(self.sb.home, "otra"))["error"], "hide.otherDisk")
        self.assertTrue(back(os.path.join(disk, "x", "Mias"))["ok"])
        self.assertTrue(self.sb.helper("unprotect", hid, stdin=KEY + "\n")["ok"])
        self.assertEqual(os.lstat(os.path.join(disk, "x", "Mias", "f")).st_ino, ino)
        self.assertFalse(os.path.exists(hidden))
        shutil.rmtree(os.path.join(disk, "x", "Mias"))
        r = mk(os.path.join(disk, "x", "Okx"), mode="visible")
        self.assertTrue(r["ok"], r)
        fid, path, rec = r["data"]["id"], r["data"]["path"], r["data"]["recoveryKey"]
        vault = os.path.join(hidden, "vaults", fid)
        self.assertTrue(os.path.isfile(os.path.join(vault, "gocryptfs.conf")))
        self.assertFalse(os.path.exists(os.path.join(self.sb.data, "vaults", fid)))   # nada en el disco interno
        self.assertEqual(mk(os.path.join(hidden, "y"))["error"], "path.taken")
        self.assertEqual(self.sb.helper("status")["data"]["total"], 1)
        r = self.sb.helper("unlock", fid, stdin=KEY + "\n"); self.assertTrue(r["ok"], r)
        with open(os.path.join(path, "a.txt"), "w") as f:
            f.write("en el disco")
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        self.assertEqual(os.listdir(path), [])
        # lo suelto se aparta en el mismo disco, no en el home
        with open(os.path.join(path, "suelto.txt"), "w") as f:
            f.write("s")
        self.assertEqual(self.sb.helper("unlock", fid, stdin=KEY + "\n")["data"]["rescued"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.sb.data, "strays")))
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        self.assertTrue(self.sb.helper("unlock", fid, "recovery", stdin=rec + "\n")["ok"])
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        # disco desconectado: se dice, y borrar NO pierde el registro
        os.rename(disk, disk + ".off")
        for cmd, si in ((["unlock", fid], KEY + "\n"), (["passwd", fid], KEY + "\notra-123\n"), (["destroy", fid], "")):
            self.assertEqual(self.sb.helper(*cmd, stdin=si)["error"], "disk.missing", cmd)
        self.assertFalse(os.path.exists(disk))                                        # nada escrito en el hueco
        self.assertEqual(len(self.sb.helper("list")["data"]["folders"]), 1)
        os.rename(disk + ".off", disk)
        # registro perdido: se encuentra en el disco y vuelve
        self.assertTrue(self.sb.helper("forget", fid)["ok"])
        self.assertEqual(self.sb.helper("orphans")["data"], {"ids": [fid], "disks": {fid: "Box"}})
        self.assertTrue(self.sb.helper("readd", fid, stdin=KEY + "\n" + json.dumps({"path": path}) + "\n")["ok"])
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        with open(os.path.join(path, "a.txt")) as f:
            self.assertEqual(f.read(), "en el disco")
        # un registro editado a mano no hace que destroy borre otra ruta
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        reg_path = os.path.join(self.sb.data, "folders.sfldb")
        with open(reg_path) as f:
            good = f.read()
        victim = os.path.join(self.sb.home, "importante"); os.makedirs(victim)
        with open(reg_path, "w") as f:
            f.write(good.replace(vault, victim))
        self.sb.helper("destroy", fid)
        self.assertTrue(os.path.isdir(victim))
        with open(reg_path, "w") as f:
            f.write(good)
        self.assertTrue(self.sb.helper("destroy", fid)["ok"])
        self.assertFalse(os.path.exists(hidden))        # al irse la última, el disco queda limpio

    def make_full(self, mode="visible"):
        os.makedirs(os.path.join(self.sb.home, "P"), exist_ok=True)
        r = self.sb.helper("init", stdin=KEY + "\n" + json.dumps({"path": os.path.join(self.sb.home, "P", "x"), "mode": mode}) + "\n")
        fid, path = r["data"]["id"], r["data"]["path"]
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        os.makedirs(os.path.join(path, "sub dir", "vacía"))
        with open(os.path.join(path, "sub dir", "Ñ.bin"), "wb") as f:
            f.write(os.urandom(3 << 20))
        with open(os.path.join(path, "a.txt"), "w") as f:
            f.write("contenido")
        os.symlink("a.txt", os.path.join(path, "enlace"))
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        return fid, path, os.path.join(self.sb.data, "vaults", fid)

    def leftovers(self, path, fid):
        self.assertEqual([n for n in os.listdir(os.path.dirname(path)) if ".sfl-" in n], [])
        self.assertFalse(self.sb.mounted(os.path.join(self.sb.run, "super-folder-lock", "unprotect-" + fid)))

    def test_unprotect_keeps_every_file(self):
        for mode in ("visible", "hidden"):
            fid, path, vault = self.make_full(mode)
            self.assertEqual(self.sb.helper("unprotect", fid, stdin="mala\n")["error"], "key.wrong")
            self.leftovers(path, fid)
            self.assertTrue(os.path.isdir(vault))
            self.assertEqual(os.path.isdir(path), mode == "visible")
            r = self.sb.helper("unprotect", fid, stdin=KEY + "\n")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["data"]["files"], 3)
            self.assertEqual(sorted(os.listdir(path)), ["a.txt", "enlace", "sub dir"])      # sin el testigo
            with open(os.path.join(path, "a.txt")) as f:
                self.assertEqual(f.read(), "contenido")
            self.assertEqual(os.path.getsize(os.path.join(path, "sub dir", "Ñ.bin")), 3 << 20)
            self.assertEqual(os.readlink(os.path.join(path, "enlace")), "a.txt")
            self.assertTrue(os.path.isdir(os.path.join(path, "sub dir", "vacía")))
            self.assertFalse(self.sb.mounted(path))
            self.assertFalse(os.path.exists(vault))
            self.assertEqual(self.sb.helper("list")["data"]["folders"], [])
            self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [])
            self.leftovers(path, fid)
            shutil.rmtree(path)

    def test_unprotect_refuses(self):
        fid, path, vault = self.make_full()
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        self.assertEqual(self.sb.helper("unprotect", fid, stdin=KEY + "\n")["error"], "folder.isOpen")
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        with open(os.path.join(path, "suelto"), "w"):
            pass
        self.assertEqual(self.sb.helper("unprotect", fid, stdin=KEY + "\n")["error"], "unprotect.notEmpty")
        os.unlink(os.path.join(path, "suelto"))
        self.assertTrue(os.path.isdir(vault))

    def broken(self, patch, fid):
        """El mismo auxiliar con una avería inyectada."""
        code = ("import os,sys,shutil\nsys.path.insert(0,%r)\nimport folderlock as f\n%s\nsys.exit(f.main(['x','unprotect',%r]))"
                % (os.path.dirname(os.path.abspath(HELPER)), patch, fid))
        return subprocess.Popen(["python3", "-I", "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.sb.env)

    def test_unprotect_failures_lose_nothing(self):
        fid, path, vault = self.make_full()
        patches = {
            # una copia que sale corrupta (mismo tamaño), un archivo que falta, disco lleno
            "unprotect.failed": ["_c=shutil.copytree\ndef c(a,b,*x,**k):\n r=_c(a,b,*x,**k)\n t=os.path.join(b,'a.txt')\n if os.path.exists(t):\n  h=open(t,'r+'); h.write('X'); h.close()\n return r\nshutil.copytree=c",
                                 "_c=shutil.copytree\ndef c(a,b,*x,**k):\n r=_c(a,b,*x,**k)\n t=os.path.join(b,'sub dir','Ñ.bin')\n if os.path.exists(t): os.unlink(t)\n return r\nshutil.copytree=c",
                                 "def c(a,b,*x,**k):\n os.mkdir(b); open(os.path.join(b,'parcial'),'w').close(); raise OSError(28,'ENOSPC')\nshutil.copytree=c",
                                 "def r(a,b): raise OSError(5,'EIO')\nos.rename=r"],
            "unprotect.space": ["class S: f_bavail=1; f_frsize=1\nos.statvfs=lambda p: S"],
        }
        for err, ps in patches.items():
            for patch in ps:
                out, e = self.broken(patch, fid).communicate(KEY + "\n", timeout=60)
                self.assertEqual(json.loads(out)["error"], err, patch + e)
                self.leftovers(path, fid)
                self.assertTrue(os.path.isfile(os.path.join(vault, "gocryptfs.conf")))
                self.assertEqual(os.listdir(path), [])                    # visible y vacía, como estaba
                self.assertEqual(len(self.sb.helper("list")["data"]["folders"]), 1)
        # tras todo eso, los archivos siguen ahí
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        with open(os.path.join(path, "a.txt")) as f:
            self.assertEqual(f.read(), "contenido")
        self.assertEqual(os.path.getsize(os.path.join(path, "sub dir", "Ñ.bin")), 3 << 20)
        self.assertTrue(self.sb.helper("lock", fid)["ok"])

    def test_unprotect_killed_midway(self):
        import signal, time
        fid, path, vault = self.make_full()
        slow = "import time\n_c=shutil.copytree\ndef c(a,b,*x,**k):\n r=_c(a,b,*x,**k)\n if b.endswith(%r): time.sleep(20)\n return r\nshutil.copytree=c" % (".x.sfl-" + fid)
        staging = os.path.join(os.path.dirname(path), ".x.sfl-" + fid)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            p = self.broken(slow, fid)
            p.stdin.write(KEY + "\n"); p.stdin.flush()
            for _ in range(100):
                if os.path.exists(os.path.join(staging, "a.txt")):
                    break
                time.sleep(0.05)
            time.sleep(0.5)
            # mientras tanto no se puede abrir (dos montajes de la misma bóveda) y lockall no la estropea
            self.assertEqual(self.sb.helper("unlock", fid, stdin=KEY + "\n")["error"], "folder.unprotecting")
            self.assertTrue(self.sb.helper("lockall")["ok"])
            self.assertTrue(os.path.exists(staging))
            p.send_signal(sig); p.communicate(timeout=30)
            if sig == signal.SIGKILL:                                      # sin aviso: queda en claro…
                self.assertTrue(os.path.exists(staging))
                self.assertTrue(self.sb.helper("lockall")["ok"])           # …hasta el siguiente arranque
            self.leftovers(path, fid)
            self.assertTrue(os.path.isfile(os.path.join(vault, "gocryptfs.conf")))
        self.assertTrue(self.sb.helper("unprotect", fid, stdin=KEY + "\n")["ok"])
        with open(os.path.join(path, "a.txt")) as f:
            self.assertEqual(f.read(), "contenido")

    def test_check_path(self):
        check = lambda p: self.sb.helper("check", stdin=json.dumps({"path": p}) + "\n")
        h = self.sb.home
        os.makedirs(os.path.join(h, "vacia")); os.makedirs(os.path.join(h, "llena", "x"))
        self.assertEqual(check(os.path.join(h, "vacia"))["data"], {"state": "empty", "canHide": True})
        self.assertEqual(check(os.path.join(h, "nueva"))["data"], {"state": "new", "canHide": True})
        self.assertEqual(check(os.path.join(h, "llena"))["data"]["state"], "full")
        os.makedirs(os.path.join(h, ".config", "app"))
        self.assertEqual(check(os.path.join(h, ".config"))["error"], "path.system")
        self.assertEqual(check(os.path.join(h, "no", "hay"))["error"], "path.parentMissing")
        self.assertEqual(check(h)["error"], "path.outsideHome")
        self.assertFalse(os.path.exists(os.path.join(h, "nueva")))        # solo mira

    # ------------------------------------------------------------ tipo «esconder»
    FILES = {"a.txt": b"contenido", "sub dir/\u00d1 foto.bin": bytes(range(256)) * 900, "sub dir/hondo/vac\u00edo.txt": b"", ".oculto": b"x"}

    def originals(self):
        path = os.path.join(self.sb.home, "Q", "Fotos")
        for rel, data in self.FILES.items():
            os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
            with open(os.path.join(path, rel), "wb") as f:
                f.write(data)
        os.makedirs(os.path.join(path, "carpeta vac\u00eda"), exist_ok=True)
        if not os.path.lexists(os.path.join(path, "enlace")):
            os.symlink("a.txt", os.path.join(path, "enlace"))
        os.chmod(os.path.join(path, "a.txt"), 0o640)
        os.chmod(path, 0o755)
        return path

    def snap(self, root):
        """Todo lo que identifica a los archivos: i-nodo, permisos, fecha y contenido."""
        out = {}
        for base, dirs, files in os.walk(root):
            for n in dirs + files:
                full = os.path.join(base, n); st = os.lstat(full)
                data = None
                if os.path.isfile(full) and not os.path.islink(full):
                    with open(full, "rb") as f:
                        data = f.read()
                out[os.path.relpath(full, root)] = (st.st_ino, st.st_mode, st.st_mtime_ns, data)
        return out

    def hide(self, path, mode="visible", key=KEY):
        return self.sb.helper("init", stdin=key + "\n" + json.dumps({"path": path, "type": "hide", "mode": mode}) + "\n")

    def store(self, fid):
        return os.path.join(self.sb.data, "locked", fid)

    def test_hide_moves_without_touching_files(self):
        for mode in ("visible", "hidden"):
            path = self.originals()
            before = self.snap(path); top = os.lstat(path)
            r = self.hide(path, mode)
            self.assertTrue(r["ok"], r)
            fid = r["data"]["id"]
            self.assertEqual(r["data"]["recoveryKey"], "")
            self.assertEqual(os.path.isdir(path), mode == "visible")
            if mode == "visible":
                self.assertEqual(os.listdir(path), [])
            self.assertEqual(os.stat(self.store(fid)).st_mode & 0o777, 0)
            with self.assertRaises(OSError):
                os.listdir(self.store(fid))
            self.assertEqual(self.sb.helper("status")["data"], {"open": [], "total": 1})
            # ni la clave ni su huella salen
            self.assertNotIn(KEY, json.dumps(self.sb.helper("list")))
            self.assertNotIn("hash", json.dumps(self.sb.helper("list")) + json.dumps(self.sb.helper("info", fid)))
            self.assertEqual(self.sb.helper("info", fid)["data"]["type"], "hide")
            self.assertEqual(self.sb.helper("unlock", fid, stdin="mala\n")["error"], "key.wrong")
            self.assertEqual(self.sb.helper("unlock", fid, stdin=KEY + "\n")["data"]["already"], False)
            self.assertEqual(self.snap(path), before)                       # MISMOS archivos: i-nodo, permisos, fecha
            self.assertEqual((os.lstat(path).st_ino, os.lstat(path).st_mode), (top.st_ino, top.st_mode))
            self.assertEqual(self.sb.helper("status")["data"]["open"], [fid])
            self.assertFalse(os.path.exists(self.store(fid)))
            self.assertEqual(self.sb.helper("forget", fid)["error"], "folder.isOpen")
            self.assertEqual(self.sb.helper("destroy", fid)["error"], "destroy.failed")
            self.assertTrue(self.sb.helper("lock", fid)["data"]["wasOpen"])
            self.assertFalse(self.sb.helper("lock", fid)["data"]["wasOpen"])   # dos veces: no pasa nada
            # cambiar clave
            self.assertEqual(self.sb.helper("passwd", fid, stdin="mala\nnueva-1\n")["error"], "key.wrong")
            self.assertTrue(self.sb.helper("passwd", fid, stdin=KEY + "\nnueva-1\n")["ok"])
            self.assertEqual(self.sb.helper("unlock", fid, stdin=KEY + "\n")["error"], "key.wrong")
            # quitar protección: vuelve tal cual, sin copiar
            self.assertEqual(self.sb.helper("unprotect", fid, stdin="mala\n")["error"], "key.wrong")
            self.assertTrue(self.sb.helper("unprotect", fid, stdin="nueva-1\n")["ok"])
            self.assertEqual(self.snap(path), before)
            self.assertEqual(self.sb.helper("list")["data"]["folders"], [])
            self.assertEqual(os.listdir(os.path.join(self.sb.data, "locked")), [])
            shutil.rmtree(path)

    def test_hide_open_file_next_one_fails(self):
        path = self.originals()
        fid = self.hide(path)["data"]["id"]
        self.sb.helper("unlock", fid, stdin=KEY + "\n")
        with open(os.path.join(path, "a.txt")) as f:
            self.assertTrue(self.sb.helper("lock", fid)["ok"])
            with self.assertRaises(FileNotFoundError):
                open(os.path.join(path, ".oculto"))
            f.read()

    def test_hide_reboot_locks_by_registry(self):
        """Equipo apagado con una abierta: run_dir ya no existe y aun así el arranque la bloquea."""
        path = self.originals()
        fid = self.hide(path, "hidden")["data"]["id"]
        self.sb.helper("unlock", fid, stdin=KEY + "\n")
        shutil.rmtree(os.path.join(self.sb.run, "super-folder-lock"))
        self.assertEqual(self.sb.helper("lockall")["data"]["locked"], [fid])
        self.assertFalse(os.path.exists(path))

    def test_hide_strays_and_update(self):
        path = self.originals()
        fid = self.hide(path)["data"]["id"]
        with open(os.path.join(path, "suelto.txt"), "w") as f:
            f.write("s")
        self.assertEqual(self.sb.helper("unlock", fid, stdin="mala\n")["error"], "key.wrong")
        self.assertEqual(os.listdir(path), ["suelto.txt"])
        self.assertEqual(self.sb.helper("unlock", fid, stdin=KEY + "\n")["data"]["rescued"], 1)
        r = [n for n in os.listdir(path) if n.startswith("rescued ")]
        self.assertTrue(os.path.exists(os.path.join(path, r[0], "suelto.txt")))
        self.assertTrue(os.path.exists(os.path.join(path, "a.txt")))
        # cambiar de modo ABIERTA no toca la carpeta; vacía y abierta, tampoco
        self.assertTrue(self.sb.helper("update", fid, stdin=json.dumps({"mode": "hidden"}) + "\n")["ok"])
        self.assertTrue(os.path.exists(os.path.join(path, "a.txt")))
        self.assertTrue(self.sb.helper("lock", fid)["ok"])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(self.sb.helper("update", fid, stdin=json.dumps({"mode": "visible"}) + "\n")["ok"])
        self.assertEqual(os.listdir(path), [])

    def test_hide_rejects(self):
        h = self.sb.home
        os.makedirs(os.path.join(h, ".local", "z"), exist_ok=True)
        os.makedirs(os.path.join(h, ".config", "x")); os.makedirs(os.path.join(h, "real", "y")); os.symlink(os.path.join(h, "real"), os.path.join(h, "enlace"))
        for path, err in ((h, "path.outsideHome"), (os.path.join(h, ".config"), "path.system"), (os.path.join(h, "enlace", "y"), "path.outsideHome"),
                          (os.path.join(h, ".local"), "path.system"), ("/tmp", "path.outsideHome")):
            self.assertEqual(self.hide(path)["error"], err, path)
        path = self.originals()
        self.assertTrue(self.hide(path)["ok"])
        self.assertEqual(self.hide(path)["error"], "path.taken")
        self.assertEqual(self.hide(os.path.dirname(path))["error"], "path.taken")
        # cifrar, en cambio, sigue exigiendo vacía (no copia)
        os.makedirs(os.path.join(h, "llena", "x"))
        r = self.sb.helper("init", stdin=KEY + "\n" + json.dumps({"path": os.path.join(h, "llena"), "type": "encrypt"}) + "\n")
        self.assertEqual(r["error"], "path.notEmpty")

    def test_hide_lost_registry(self):
        path = self.originals(); before = self.snap(path)
        fid = self.hide(path)["data"]["id"]
        with open(os.path.join(self.sb.data, "folders.sfldb"), "w") as f:
            f.write("SFLDB 1\n" + json.dumps({"schemaVersion": 1, "folders": {}}))
        self.assertTrue(self.sb.helper("lockall")["ok"])
        self.assertEqual(self.sb.helper("orphans")["data"], {"ids": [fid], "disks": {fid: ""}})
        si = lambda k: k + "\n" + json.dumps({"path": path, "mode": "hidden"}) + "\n"
        self.assertEqual(self.sb.helper("readd", fid, stdin=si("mala"))["error"], "key.wrong")
        self.assertTrue(self.sb.helper("readd", fid, stdin=si(KEY))["ok"])
        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
        self.assertEqual(self.snap(path), before)
        # olvidar y volver a agregar
        self.assertTrue(self.sb.helper("lock", fid)["ok"]); self.assertTrue(self.sb.helper("forget", fid)["ok"])
        self.assertEqual(self.sb.helper("orphans")["data"]["ids"], [fid])
        self.assertTrue(self.sb.helper("readd", fid, stdin=si(KEY))["ok"])

    def test_hide_never_copies(self):
        """Si moverla exigiera copiar (otro disco), se rechaza; y el contenido no pasa por shutil."""
        path = self.originals(); before = self.snap(path)
        for patch in ("def x(p): return False\nf.hide_device_ok=x", "_r=os.rename\ndef r(a,b):\n if b.endswith('/data'): raise OSError(18,'EXDEV')\n return _r(a,b)\nos.rename=r"):
            out = self.run_patched(patch, ["init"], KEY + "\n" + json.dumps({"path": path, "type": "hide"}) + "\n")
            self.assertIn(json.loads(out)["error"], ("hide.otherDisk", "lock.failed"))
            self.assertEqual(self.snap(path), before)
            self.assertEqual(self.sb.helper("list")["data"]["folders"], [])
            self.assertEqual(os.listdir(os.path.join(self.sb.data, "locked")) if os.path.isdir(os.path.join(self.sb.data, "locked")) else [], [])
        boom = "def b(*a,**k): raise AssertionError('copia')\nfor n in ('copy','copy2','copyfile','copytree','rmtree'): setattr(shutil,n,b)"
        fid = json.loads(self.run_patched(boom, ["init"], KEY + "\n" + json.dumps({"path": path, "type": "hide"}) + "\n"))["data"]["id"]
        for cmd in (["unlock", fid], ["lock", fid], ["unprotect", fid]):
            self.assertTrue(json.loads(self.run_patched(boom, cmd, KEY + "\n"))["ok"], cmd)
        self.assertEqual(self.snap(path), before)

    def run_patched(self, patch, args, stdin, rc=None):
        code = ("import os,sys,shutil\nsys.path.insert(0,%r)\nimport folderlock as f\n%s\nsys.exit(f.main(['x']+%r))"
                % (os.path.dirname(os.path.abspath(HELPER)), patch, args))
        p = subprocess.run(["python3", "-I", "-c", code], input=stdin, capture_output=True, text=True, env=self.sb.env, timeout=60)
        if rc is not None:
            rc.append(p.returncode)
        return p.stdout

    def test_hide_killed_at_every_step(self):
        wrap = ("N=%d\nc=[0]\ndef w(o,n):\n r=getattr(o,n)\n def g(*a,**k):\n  c[0]+=1\n  if c[0]==N: os.kill(os.getpid(),9)\n  return r(*a,**k)\n setattr(o,n,g)\n"
                "for o,n in ((os,'rename'),(os,'replace'),(os,'mkdir'),(os,'rmdir'),(os,'chmod'),(os,'unlink'),(os,'makedirs'),(f,'write_registry'),(f,'write_atomic'),(f,'move_children')): w(o,n)")
        path = self.originals(); before = self.snap(path)
        kills = 0
        for op in ("init", "unlock", "lock", "passwd", "unprotect", "forget"):
            n = 0
            while True:
                n += 1
                self.assertLess(n, 80)
                # estado de partida de cada intento
                fid = None
                if op != "init":
                    fid = self.hide(path)["data"]["id"]
                    if op == "lock":
                        self.assertTrue(self.sb.helper("unlock", fid, stdin=KEY + "\n")["ok"])
                    if op == "unlock":
                        with open(os.path.join(path, "suelto"), "w") as fh:
                            fh.write("suelto")
                rc = []
                si = {"init": KEY + "\n" + json.dumps({"path": path, "type": "hide", "mode": "visible"}) + "\n",
                      "passwd": KEY + "\nnueva-1\n"}.get(op, KEY + "\n")
                self.run_patched(wrap % n, [op] + ([fid] if fid else []), si, rc)
                where = "%s paso %d" % (op, n)
                self.assertTrue(self.sb.helper("lockall")["ok"], where)          # el siguiente arranque
                folders = self.sb.helper("list")["data"]["folders"]
                for o in self.sb.helper("orphans")["data"]["ids"]:                # olvidada: se recupera
                    self.assertTrue(self.sb.helper("readd", o, stdin=KEY + "\n" + json.dumps({"path": path}) + "\n")["ok"], where)
                folders = self.sb.helper("list")["data"]["folders"]
                if folders:
                    g = folders[0]["id"]
                    tries = [self.sb.helper("unprotect", g, stdin=k + "\n") for k in (KEY, "nueva-1")]
                    self.assertTrue(any(x["ok"] for x in tries), (where, tries, os.listdir(path) if os.path.isdir(path) else None))
                got = self.snap(path)
                extra = {k for k in got if k.startswith("rescued ")}
                if op == "unlock":
                    self.assertEqual([got[k][3] for k in extra if k.endswith("/suelto")], [b"suelto"], where)
                self.assertEqual({k: v for k, v in got.items() if k not in extra}, {k: v for k, v in before.items()}
                                 if not extra else {k: v for k, v in before.items()}, where)
                self.assertEqual(self.sb.helper("list")["data"]["folders"], [], where)
                for k in [x for x in os.listdir(path) if x.startswith("rescued ")]:
                    shutil.rmtree(os.path.join(path, k))
                locked = os.path.join(self.sb.data, "locked")
                self.assertEqual([x for x in (os.listdir(locked) if os.path.isdir(locked) else []) if not x.endswith(".json") and not x.startswith(".tmp")], [], where)
                for base in (self.sb.data, locked):                              # restos de la muerte (los quita el arranque, a la hora)
                    for x in os.listdir(base) if os.path.isdir(base) else []:
                        if x.startswith(".tmp-") or (base == locked and x.endswith(".json")):
                            os.unlink(os.path.join(base, x))
                if rc[0] != -9:
                    break
                kills += 1
        self.assertGreater(kills, 40)
        print("escondida, muertes probadas:", kills)

    def test_without_gocryptfs(self):
        self.sb.add_folder()
        env = dict(self.sb.env, PATH="/nonexistent")
        for args, stdin in ((["unlock", FID], KEY + "\n"), (["init"], KEY + "\n{}\n")):
            p = subprocess.run(["/usr/bin/python3", "-I", HELPER] + args, input=stdin, capture_output=True,
                               text=True, env=env, timeout=30)
            self.assertEqual(json.loads(p.stdout)["error"], "gocryptfs.missing", args)

    def test_unknown_and_missing_key(self):
        self.sb.add_folder()
        self.assertEqual(self.sb.helper("unlock", "../../etc")["error"], "folder.unknown")
        self.assertEqual(self.sb.helper("unlock", FID, stdin="")["error"], "key.empty")
        self.assertEqual(self.sb.helper("nope")["error"], "command.unknown")


if __name__ == "__main__":
    unittest.main(verbosity=1)
