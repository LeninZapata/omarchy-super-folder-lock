"""bin/visiblewatch.py: avisa solo si el IN_OPEN viene con una ventana de Nautilus con el
nombre de la carpeta. `hyprctl` es falso (SFL_HYPRCTL), controlado por el test."""
import ctypes
import ctypes.util
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_folderlock import Sandbox, FID, KEY  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "..", "bin", "visiblewatch.py")
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
import visiblewatch  # noqa: E402


class VisibleWatchTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.clean)
        self.path = self.sb.add_folder(rel="Diario")
        reg_path = os.path.join(self.sb.data, "folders.sfldb")
        with open(reg_path) as f:
            reg = json.loads(f.read().partition("\n")[2])
        reg["folders"][FID]["mode"] = "visible"
        with open(reg_path, "w") as f:
            f.write("SFLDB 1\n" + json.dumps(reg))
        os.mkdir(self.path)  # visible bloqueada = carpeta vacía en su sitio
        self.clients = os.path.join(self.sb.base, "clients.json")
        with open(self.clients, "w") as f:
            f.write("[]")
        fake = os.path.join(self.sb.base, "hyprctl")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\ncat '%s'\n" % self.clients)
        os.chmod(fake, 0o755)
        # Lo que Files dice por D-Bus que muestra (busctl falso)
        self.locations = os.path.join(self.sb.base, "locations.json")
        self.set_locations([])
        bus = os.path.join(self.sb.base, "busctl")
        with open(bus, "w") as f:
            f.write("#!/bin/sh\ncat '%s'\n" % self.locations)
        os.chmod(bus, 0o755)
        env = dict(self.sb.env, SFL_HYPRCTL=fake, SFL_BUSCTL=bus)
        self.proc = subprocess.Popen(["python3", "-I", WATCH], stdout=subprocess.PIPE, text=True, env=env)
        # al acabar (orden inverso): matar → esperar → cerrar la tubería
        self.addCleanup(self.proc.stdout.close)
        self.addCleanup(self.proc.wait)
        self.addCleanup(self.proc.kill)
        time.sleep(0.8)

    def line(self, timeout):
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        return self.proc.stdout.readline().strip() if r else None

    def set_window(self, title, pid=None):
        win = {"class": "org.gnome.Nautilus", "title": title, "address": "0xabc"}
        if pid is not None:
            win["pid"] = pid
        with open(self.clients, "w") as f:
            json.dump([win], f)

    def set_locations(self, paths):
        with open(self.locations, "w") as f:
            json.dump({"type": "a{sas}", "data": {"/org/gnome/Nautilus/window/1": ["file://" + p for p in paths]}}, f)

    def watch_as_nautilus(self, path):
        """Este proceso hace de Nautilus: vigila (inotify) la carpeta que «muestra»."""
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fd = libc.inotify_init1(os.O_CLOEXEC)
        self.assertGreaterEqual(fd, 0)
        self.watch_fds = getattr(self, "watch_fds", []) + [fd]
        self.addCleanup(self.stop_watching)
        self.assertGreaterEqual(libc.inotify_add_watch(fd, path.encode(), 0x2 | 0x100 | 0x200), 0)
        return os.getpid()

    def test_indexer_open_is_ignored(self):
        os.listdir(self.path)           # como find / localsearch: sin ventana
        self.assertIsNone(self.line(2.5))

    def test_nautilus_open_is_reported(self):
        self.set_window("Diario")
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)
        os.listdir(self.path)           # repetido enseguida: silencio (QUIET_SECONDS)
        self.assertIsNone(self.line(1.5))

    def test_other_window_name_is_ignored(self):
        self.set_window("Otra carpeta")
        os.listdir(self.path)
        self.assertIsNone(self.line(2.5))

    def test_path_created_after_registry_is_watched(self):
        os.rmdir(self.path)              # la ruta aparece DESPUÉS del registro (carrera de init)
        time.sleep(0.5)
        os.mkdir(self.path)
        time.sleep(5.5)                  # reintento del vigilante
        self.set_window("Diario")
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)

    def test_open_folder_is_not_watched(self):
        os.rmdir(self.path)
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])  # abierta: no se vigila
        time.sleep(0.6)
        self.set_window("Diario")
        os.listdir(self.path)
        self.assertIsNone(self.line(2.5))
        self.assertTrue(self.sb.helper("lock", FID)["ok"])

    def stop_watching(self):
        while getattr(self, "watch_fds", []):
            os.close(self.watch_fds.pop())

    def lock_with_window_inside(self):
        """Abierta con Nautilus dentro; al bloquearse, esa ventana sigue llamándose «Diario»."""
        os.rmdir(self.path)
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        time.sleep(0.6)
        self.set_window("Diario")
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        time.sleep(0.8)

    def test_window_already_inside_at_lock_is_ignored(self):
        self.lock_with_window_inside()
        os.listdir(self.path)           # Nautilus relee la carpeta al bloquearse: no es doble clic
        self.assertIsNone(self.line(2.5))

    def test_window_in_a_subfolder_at_lock_is_ignored_after_f5(self):
        # Estaba en Diario/fotos: se llama «fotos»; con el F5 sube a Diario, que no es doble clic
        os.rmdir(self.path)
        self.assertTrue(self.sb.helper("unlock", FID, stdin=KEY + "\n")["ok"])
        time.sleep(0.6)
        self.set_window("fotos")
        self.set_locations([os.path.join(self.path, "fotos")])
        self.assertTrue(self.sb.helper("lock", FID)["ok"])
        time.sleep(0.8)
        self.set_window("Diario", self.watch_as_nautilus(self.path))
        os.listdir(self.path)
        self.assertIsNone(self.line(2.5))

    def test_window_that_left_and_came_back_is_reported(self):
        self.lock_with_window_inside()
        self.set_window("Documentos")    # sale a la carpeta de arriba…
        time.sleep(1.5)
        self.set_window("Diario")        # …y vuelve a entrar con doble clic
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)

    def test_parent_with_the_same_name_is_ignored(self):
        # Diario/Diario: Nautilus muestra la de ARRIBA y abre las subcarpetas para contarlas
        pid = self.watch_as_nautilus(os.path.dirname(self.path))
        self.set_window("Diario", pid)
        os.listdir(self.path)
        self.assertIsNone(self.line(2.5))

    def test_window_showing_the_folder_is_reported(self):
        pid = self.watch_as_nautilus(self.path)
        self.set_window("Diario", pid)
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)

    def test_back_to_a_parent_with_the_same_name_and_in_again_is_reported(self):
        # Diario/Diario: al volver arriba el título NO cambia; lo que cambia es qué vigila
        self.set_window("Diario", self.watch_as_nautilus(self.path))
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)
        self.stop_watching()             # cancela la tarjeta y sale a la de arriba
        time.sleep(3.5)                  # pasa QUIET_SECONDS
        self.watch_as_nautilus(self.path)  # vuelve a entrar con doble clic
        os.listdir(self.path)
        self.assertEqual(self.line(3), "open %s 0xabc" % FID)


class FilesRefreshTest(unittest.TestCase):
    def test_every_files_window_of_the_folder_gets_f5_and_no_other(self):
        base = tempfile.mkdtemp(prefix="sfl-test-", dir="/tmp")
        self.addCleanup(shutil.rmtree, base)
        wins = [("org.gnome.Nautilus", "Diario", "0xa1"), ("org.gnome.Nautilus", "Diario", "0xa2"),
                ("org.gnome.Nautilus", "Otra", "0xa3"), ("Alacritty", "Diario", "0xa4"),
                ("org.gnome.Nautilus", "Diario", '0xa5" })--')]
        with open(os.path.join(base, "clients.json"), "w") as f:
            json.dump([{"class": c, "title": t, "address": a} for c, t, a in wins], f)
        fake = os.path.join(base, "hyprctl")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nif [ "$1" = clients ]; then cat "%s/clients.json"; else echo "$2" >> "%s/sent"; fi\n' % (base, base))
        os.chmod(fake, 0o755)
        subprocess.run(["python3", "-I", os.path.join(HERE, "..", "bin", "filesrefresh.py"), "/algo/Diario/"],
                       env=dict(os.environ, SFL_HYPRCTL=fake, SFL_BUSCTL=shutil.which("true")), check=True, timeout=10)
        with open(os.path.join(base, "sent")) as f:
            sent = f.read().splitlines()
        self.assertEqual(sent, ['hl.dsp.send_shortcut({ mods = "", key = "F5", window = "address:%s" })' % a
                                for a in ("0xa1", "0xa2")])

    def test_files_window_in_a_subfolder_gets_f5(self):
        # Files dice qué ruta muestra cada ventana; el título es solo el nombre de la subcarpeta
        base = tempfile.mkdtemp(prefix="sfl-test-", dir="/tmp")
        self.addCleanup(shutil.rmtree, base)
        wins = [("org.gnome.Nautilus", "v", "0xb1"), ("org.gnome.Nautilus", "fotos", "0xb2"),
                ("org.gnome.Nautilus", "otra", "0xb3")]
        with open(os.path.join(base, "clients.json"), "w") as f:
            json.dump([{"class": c, "title": t, "address": a} for c, t, a in wins], f)
        uris = ["file:///algo/Diario/a%20b/v", "file:///algo/Diario2/otra", "file:///algo/fotos"]
        with open(os.path.join(base, "locations.json"), "w") as f:
            json.dump({"type": "a{sas}", "data": {"/w/1": uris[:1], "/w/2": uris[1:]}}, f)
        fake = os.path.join(base, "hyprctl")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nif [ "$1" = clients ]; then cat "%s/clients.json"; else echo "$2" >> "%s/sent"; fi\n' % (base, base))
        bus = os.path.join(base, "busctl")
        with open(bus, "w") as f:
            f.write('#!/bin/sh\ncat "%s/locations.json"\n' % base)
        for x in (fake, bus):
            os.chmod(x, 0o755)
        subprocess.run(["python3", "-I", os.path.join(HERE, "..", "bin", "filesrefresh.py"), "/algo/Diario"],
                       env=dict(os.environ, SFL_HYPRCTL=fake, SFL_BUSCTL=bus), check=True, timeout=10)
        with open(os.path.join(base, "sent")) as f:
            sent = f.read().splitlines()
        self.assertEqual(sent, ['hl.dsp.send_shortcut({ mods = "", key = "F5", window = "address:0xb1" })'])


class FilesOpenTest(unittest.TestCase):
    """--open (desbloquear con «Mostrar la carpeta»): abre en Files solo si ninguna ventana la muestra."""

    def run_open(self, locations):
        base = tempfile.mkdtemp(prefix="sfl-test-", dir="/tmp")
        self.addCleanup(shutil.rmtree, base)
        with open(os.path.join(base, "clients.json"), "w") as f:
            json.dump([{"class": "org.gnome.Nautilus", "title": "Diario", "address": "0xc1"}], f)
        with open(os.path.join(base, "locations.json"), "w") as f:
            json.dump({"type": "a{sas}", "data": {"/w/1": ["file://" + p for p in locations]}}, f)
        scripts = {
            "hyprctl": '[ "$1" = clients ] && cat "%s/clients.json" || echo "$2" >> "%s/sent"' % (base, base),
            "busctl": 'cat "%s/locations.json"' % base,
            "xdg-open": 'echo "$1" >> "%s/opened"' % base,
        }
        env = dict(os.environ)
        for name, body in scripts.items():
            exe = os.path.join(base, name)
            with open(exe, "w") as f:
                f.write("#!/bin/sh\n%s\n" % body)
            os.chmod(exe, 0o755)
        env.update(SFL_HYPRCTL=os.path.join(base, "hyprctl"), SFL_BUSCTL=os.path.join(base, "busctl"),
                   SFL_XDG_OPEN=os.path.join(base, "xdg-open"))
        subprocess.run(["python3", "-I", os.path.join(HERE, "..", "bin", "filesrefresh.py"), "--open", "/algo/Diario"],
                       env=env, check=True, timeout=10)
        read = lambda n: open(os.path.join(base, n)).read().splitlines() if os.path.exists(os.path.join(base, n)) else []
        return read("sent"), read("opened")

    def test_already_shown_is_only_refreshed(self):
        sent, opened = self.run_open(["/algo/Diario"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(opened, [])

    def test_not_shown_is_opened(self):
        sent, opened = self.run_open(["/algo/Diario2", "/otra/Diario"])   # mismo nombre, otra ruta
        self.assertEqual(len(sent), 1)                                    # el F5 va por el título
        self.assertEqual(opened, ["/algo/Diario"])


class WatchesTest(unittest.TestCase):
    """En el disco del repo (btrfs en Omarchy), no en /tmp: ahí `stat` y fdinfo no coinciden."""

    def test_tells_the_shown_folder_from_its_parent(self):
        base = tempfile.mkdtemp(prefix="sfl-test-", dir=HERE)
        self.addCleanup(shutil.rmtree, base)
        inner = os.path.join(base, "in")
        os.mkdir(inner)
        w = visiblewatch.Watcher()
        self.addCleanup(os.close, w.fd)
        targets = {p: w.target(w.add(p, 0x20)) for p in (base, inner)}
        self.assertTrue(all(targets.values()))
        # otro proceso que solo muestra la de arriba
        code = ("import ctypes,sys,time;l=ctypes.CDLL(None);fd=l.inotify_init1(0);"
                "l.inotify_add_watch(fd,sys.argv[1].encode(),0x100);print(1,flush=True);time.sleep(60)")
        other = subprocess.Popen([sys.executable, "-c", code, base], stdout=subprocess.PIPE)
        self.addCleanup(other.stdout.close)
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        other.stdout.readline()
        self.assertTrue(visiblewatch.watches(other.pid, targets[base]))
        self.assertFalse(visiblewatch.watches(other.pid, targets[inner]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
