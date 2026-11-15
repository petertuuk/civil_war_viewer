"""Permanent unit numbers (roadmap T2.2): data/manual/unit_ids.tsv, `key<TAB>id`.

Database unit ids were insertion order, so one unit more or fewer in an early list renumbered everything after it, and the numbers
in viewer links (#unit=1069), the exported files and the test set pointed at other units. The registry fixes each unit's number
the first time the build sees it and never changes or reuses it:
  key  = Dyer's unit id (michigan/021_...), "nps:<unit code>" for NPS units not linked to Dyer's, or
         "manual:<side>|<echelon>|<display name>" for a unit created by a hand-made claim file;
  id   = the integer used as unit.id.
A key not in the file gets the next number after the largest one ever issued and is appended when the build ends well. A unit that
disappears from the inputs keeps its line (its number stays reserved). The file is tracked in git: commit it with the data.
If the file is missing the build starts one from the units in insertion order, which reproduces the numbers of an old database.
"""
from pathlib import Path


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.ids = {}
        if self.path.exists():
            for ln in self.path.read_text(encoding="utf-8").splitlines():
                if not ln.strip() or ln.startswith("#"):
                    continue
                key, _, num = ln.rpartition("\t")
                if key in self.ids:
                    raise ValueError(f"{self.path}: key listed twice: {key}")
                self.ids[key] = int(num)
        if len(set(self.ids.values())) != len(self.ids):
            raise ValueError(f"{self.path}: an id is used for two keys")
        self.top = max(self.ids.values(), default=0)
        self.new = []                     # (key, id) in the order issued
        self.rev = {v: k for k, v in self.ids.items()}

    def id_for(self, key):
        if key not in self.ids:
            self.top += 1
            self.ids[key] = self.top
            self.rev[self.top] = key
            self.new.append((key, self.top))
        return self.ids[key]

    def key_of(self, uid):
        return self.rev.get(uid)

    def save(self):
        """Append the new lines (header first when the file is new); returns how many were added."""
        if not self.new:
            return 0
        fresh = not self.path.exists()
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            if fresh:
                f.write("# unit registry: key<TAB>id. Never edit or renumber; the build appends new units (pipeline/unit_registry.py)\n")
            for key, num in self.new:
                f.write(f"{key}\t{num}\n")
        n, self.new = len(self.new), []
        return n
