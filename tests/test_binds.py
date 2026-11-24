"""binds.py: al cerrarse el plugin solo se suelta una tecla que es solo nuestra."""
import sys; sys.dont_write_bytecode = True
import importlib.util, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("binds", os.path.join(HERE, "..", "bin", "binds.py"))
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

D = b.DESC
assert 'DESC = "%s"' % D in open(os.path.join(HERE, "..", "Shortcut.js"), encoding="utf-8").read()
text = json.dumps([
    {"modmask": 68, "key": "K", "description": D, "submap": ""},               # nuestra, sola
    {"modmask": 65, "key": "L", "description": D, "submap": ""},               # nuestra, pero comparte
    {"modmask": 65, "key": "L", "description": "otra cosa", "submap": ""},
    {"modmask": 72, "key": "R", "description": D, "submap": ""},               # nuestra en el principal...
    {"modmask": 72, "key": "R", "description": "Resize", "submap": "resize"},  # ...y ajena en otro submap
    {"modmask": 64, "key": "", "keycode": 10, "description": "Workspace 1", "submap": ""},
])
own = b.owners(text)
assert own["SUPER + CTRL + K"] == {"own": 1, "foreign": 0}
assert own["SUPER + SHIFT + L"] == {"own": 1, "foreign": 1}
assert own["SUPER + 1"] == {"own": 0, "foreign": 1}
assert b.releasable(own, ["SUPER + CTRL + K", "SUPER + SHIFT + L", "SUPER + ALT + R", "SUPER + 1", "SUPER + Z"]) == ["SUPER + CTRL + K"]
assert b.owners("") is None and b.owners("{}") is None
print("binds ok")
