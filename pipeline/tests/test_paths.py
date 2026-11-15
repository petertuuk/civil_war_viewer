"""cwv/paths.py: the default arguments equal what rebuild.sh passes, and the scripts use them."""
import os
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

import _path  # noqa: F401
from cwv import paths

PIPELINE = Path(__file__).resolve().parents[1]


def rebuild_calls():
    """script -> list of argument lists, as written in rebuild.sh (comment lines skipped)."""
    calls = {}
    for ln in open(PIPELINE / "rebuild.sh", encoding="utf-8"):
        if ln.lstrip().startswith("#"):
            continue
        for m in re.finditer(r"python3 (?:pipeline/)?(\w+)\.py ([^;|>]*)", ln):
            calls.setdefault(m.group(1), []).append(shlex.split(m.group(2)))
    return calls


def expand(tok):
    if tok == "$W":
        return str(paths.WIKIDATA)
    if tok in ("$DB", "~/db/civil_war.db"):
        return str(paths.DB)
    if tok == "~/or/txt":
        return str(paths.OR_TXT)
    if tok.startswith("$SRC/"):
        return str(paths.SOURCES / tok[5:])
    if tok == ".":
        return str(paths.ROOT)
    assert not tok.startswith(("$", "~")), tok
    return str(paths.ROOT / tok)


class DefaultsMatchRebuild(unittest.TestCase):
    def test_every_default_is_what_rebuild_passes(self):
        calls = rebuild_calls()
        for name in paths.DEFAULT_ARGS:
            self.assertIn(name, calls, name)
            for args in calls[name]:
                self.assertEqual(paths.defaults(name), [expand(t) for t in args], name)

    def test_scripts_left_out_are_the_ones_with_several_different_calls_or_special_cwd(self):
        calls = rebuild_calls()
        for name, lists in calls.items():
            if name not in paths.DEFAULT_ARGS and all(l == lists[0] for l in lists):
                self.assertIn(name, ("build_db", "stamps"), f"{name} is called the same way every time: add it to DEFAULT_ARGS")

    def test_each_listed_script_uses_its_defaults_and_only_those_do(self):
        users = {}
        for p in PIPELINE.glob("*.py"):
            for m in re.finditer(r'paths\.defaults\("(\w+)"\)', p.read_text(encoding="utf-8")):
                users[m.group(1)] = p.stem
        self.assertEqual(sorted(users), sorted(paths.DEFAULT_ARGS))
        for key, stem in users.items():
            self.assertEqual(key, stem)


class Locations(unittest.TestCase):
    def run_py(self, code, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("DB", "OR_TXT", "SOURCES")}
        e.update(env)
        out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from cwv import paths; %s" % (str(PIPELINE), code)],
                             capture_output=True, text=True, env=e, check=True)
        return out.stdout.strip()

    def test_root_is_the_folder_above_pipeline(self):
        self.assertEqual(paths.ROOT, PIPELINE.parent)

    def test_environment_overrides(self):
        self.assertEqual(self.run_py("print(paths.DB)", DB="/x/y.db"), "/x/y.db")
        self.assertEqual(self.run_py("print(paths.OR_TXT)", OR_TXT="/x/or"), "/x/or")
        self.assertEqual(self.run_py("print(paths.SOURCES)", SOURCES="/x/src"), "/x/src")

    def test_without_environment_the_home_folder_is_used(self):
        self.assertTrue(self.run_py("print(paths.DB)").endswith(os.path.join("db", "civil_war.db")))
        self.assertTrue(self.run_py("print(paths.OR_TXT)").endswith(os.path.join("or", "txt")))

    def test_defaults_are_strings_and_absolute(self):
        for name in paths.DEFAULT_ARGS:
            for a in paths.defaults(name):
                self.assertIsInstance(a, str)
                self.assertTrue(os.path.isabs(a), (name, a))


if __name__ == "__main__":
    unittest.main()
