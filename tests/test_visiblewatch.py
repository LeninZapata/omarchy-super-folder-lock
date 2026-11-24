"""bin/visiblewatch.py: avisa solo si el IN_OPEN viene con una ventana de Nautilus con el
nombre de la carpeta. `hyprctl` es falso (SFL_HYPRCTL), controlado por el test."""
import json
import os
import select
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_folderlock import Sandbox, FID, KEY  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "..", "bin", "visiblewatch.py")


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
        env = dict(self.sb.env, SFL_HYPRCTL=fake)
        self.proc = subprocess.Popen(["python3", "-I", WATCH], stdout=subprocess.PIPE, text=True, env=env)
        # al acabar (orden inverso): matar → esperar → cerrar la tubería
        self.addCleanup(self.proc.stdout.close)
        self.addCleanup(self.proc.wait)
        self.addCleanup(self.proc.kill)
        time.sleep(0.8)

    def line(self, timeout):
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        return self.proc.stdout.readline().strip() if r else None

    def set_window(self, title):
        with open(self.clients, "w") as f:
            json.dump([{"class": "org.gnome.Nautilus", "title": title, "address": "0xabc"}], f)

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
