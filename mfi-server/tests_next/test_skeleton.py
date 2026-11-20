"""EPIC-00 skeleton checks for mfi_server_next (standard library only).

Every module imports, every public name raises NotImplementedError, no module
imports the old mfi_server package, the package has no __version__, and the
Dockerfile does not copy the new package.
"""
import importlib
import re
import unittest
from pathlib import Path

PKG = "mfi_server_next"
MFI_SERVER_DIR = Path(__file__).resolve().parent.parent
PKG_DIR = MFI_SERVER_DIR / PKG
DOCKERFILE = MFI_SERVER_DIR / "Dockerfile"

MODULE_NAMES = [
    "__init__", "__main__", "config", "store", "crypto", "bson", "inform",
    "devices", "tasks", "firmware", "udp_discovery", "sensors", "serial",
    "rules", "events", "alarms", "stats", "auth", "page_api", "comet",
    "compat_api", "maps", "mqtt", "mqtt_discovery", "migrate", "rules_import",
    "editor", "network_tools",
]

FUNCTIONS = {
    "__main__": ["main"],
    "rules_import": ["convert_rules"],
}

CLASSES = {}

IMPORT_OLD = re.compile(r"(?m)^\s*(?:from|import)\s+mfi_server\b")


class TestSkeleton(unittest.TestCase):
    def test_all_modules_present(self):
        found = {p.name for p in PKG_DIR.glob("*.py")}
        self.assertEqual(found, {name + ".py" for name in MODULE_NAMES})

    def test_every_module_imports(self):
        for name in MODULE_NAMES:
            with self.subTest(module=name):
                target = PKG if name == "__init__" else PKG + "." + name
                importlib.import_module(target)

    def test_no_import_of_old_package(self):
        for path in sorted(PKG_DIR.glob("*.py")):
            with self.subTest(module=path.name):
                self.assertIsNone(IMPORT_OLD.search(path.read_text(encoding="utf-8")))

    def test_package_has_no_version(self):
        pkg = importlib.import_module(PKG)
        self.assertFalse(hasattr(pkg, "__version__"))

    def test_functions_raise_not_implemented(self):
        for modname, names in FUNCTIONS.items():
            mod = importlib.import_module(PKG + "." + modname)
            for fname in names:
                with self.subTest(func=modname + "." + fname):
                    self.assertRaises(NotImplementedError, getattr(mod, fname))

    def test_classes_raise_not_implemented(self):
        for modname, classes in CLASSES.items():
            mod = importlib.import_module(PKG + "." + modname)
            for cname, methods in classes.items():
                cls = getattr(mod, cname)
                with self.subTest(cls=modname + "." + cname):
                    self.assertRaises(NotImplementedError, cls)
                for method in methods:
                    with self.subTest(method=modname + "." + cname + "." + method):
                        self.assertTrue(hasattr(cls, method))
                        self.assertRaises(NotImplementedError, getattr(cls, method), None)

    def test_dockerfile_does_not_copy_new_package(self):
        self.assertNotIn(PKG, DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
