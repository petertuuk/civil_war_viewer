"""Skip rebuild stages whose inputs have not changed (called by rebuild.sh around each stage).

    python3 pipeline/stamps.py check <stage>   exit 0: skip (inputs as at the stage's last good run); 1: run it
    python3 pipeline/stamps.py save <stage>    after a good run: record its inputs and which files it wrote

A stage's inputs: every file under data/ except the files this stage or any later one writes (learned from earlier
runs: the files whose mtime a run changed), the pipeline scripts its rebuild.sh lines name plus the pipeline modules
they import, the OR texts in ~/or/txt when its lines name them, and the database when its lines use it ("$DB" or
~/db/civil_war.db; the database counts as the inputs of the db stage that built it). Outputs are byte-identical for
the same inputs (PYTHONHASHSEED=0), so a skipped stage would only have rewritten the same files. The first run of a
stage in a session always runs. Stamps live beside the work copy (.rebuild_stamps.json, not pushed); FORCE=1 in the
environment of rebuild.sh runs every stage.
"""
import hashlib, json, os, re, sys
from pathlib import Path

ROOT = Path.cwd()
ORDER = ["units", "dyers", "events", "links", "or", "datelines", "db_build", "db_finish", "checks", "war", "review"]
STAMPS = ROOT / ".rebuild_stamps.json"
CACHE = Path.home() / ".cache" / "cwv_stamps"
DB = Path(os.environ.get("DB", str(Path.home() / "db" / "civil_war.db")))
ORTXT = Path.home() / "or" / "txt"


def load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def block(stage):
    """The rebuild.sh lines of a stage (db_build / db_finish share the db block)."""
    s = open(ROOT / "pipeline/rebuild.sh", encoding="utf-8").read()
    for m in re.finditer(r"^    ([\w|]+)\)(.*?);;", s, re.S | re.M):
        if stage in m.group(1).split("|"):
            b = m.group(2)
            if stage == "db_build":
                b = b.split('if [ "$s" != db_build ]')[0]
            elif stage == "db_finish":
                b = b.split('if [ "$s" != db_build ]')[1]
            return b
    return ""


def scripts(b):
    mods = {p.stem for p in (ROOT / "pipeline").glob("*.py")}
    todo = [x for x in re.findall(r"(\w+)\.py", b) if x in mods]
    seen = set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        src = open(ROOT / f"pipeline/{m}.py", encoding="utf-8", errors="replace").read()
        todo += [x for x in re.findall(r"^\s*(?:from|import)\s+(\w+)", src, re.M) if x in mods]
        todo += [x for x in re.findall(r"\bimport\s+(\w+)", src) if x in mods]
    return sorted(f"pipeline/{m}.py" for m in seen)


def files_under(*dirs):
    for d in dirs:
        for root, ds, fs in os.walk(d):
            ds[:] = [x for x in ds if x != "__pycache__"]
            for f in fs:
                yield os.path.join(root, f)


def md5s(paths):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = load(CACHE / "filehash.json", {})
    out = {}
    for p in paths:
        try:
            st = os.stat(p)
        except FileNotFoundError:
            continue
        k = f"{st.st_size}:{st.st_mtime_ns}"
        c = cache.get(p)
        if not c or c[0] != k:
            h = hashlib.md5()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            c = cache[p] = [k, h.hexdigest()]
        out[p] = c[1]
    json.dump(cache, open(CACHE / "filehash.json", "w"))
    return out


def input_hash(stage, stamps):
    b = block(stage)
    later = set()
    for s in ORDER[ORDER.index(stage):]:
        later |= set(stamps.get(s, {}).get("outputs", []))
    data = sorted(p for p in files_under("data") if p not in later and not p.endswith(".workcopy_tmp"))
    parts = md5s(data)
    parts.update(md5s(scripts(b) + ["pipeline/rebuild.sh"]))
    if "~/or/txt" in b:
        parts.update({f"ortxt:{k}": v for k, v in md5s(sorted(files_under(str(ORTXT)))).items()})
    if "$DB" in b or "~/db/civil_war.db" in b:
        if stage != "db_build":
            if not DB.exists():
                return None
            parts["$DB"] = (stamps.get("_db_build") if stage == "db_finish" else stamps.get("_db_version")) or "unknown"
    h = hashlib.md5(json.dumps(sorted(parts.items())).encode()).hexdigest()
    return h


def mtimes():
    out = {}
    for p in list(files_under("data", "viewer")) + ["civil_war.db"]:
        try:
            out[p] = os.stat(p).st_mtime_ns
        except FileNotFoundError:
            pass
    return out


def main(cmd, stage):
    stamps = load(STAMPS, {})
    if cmd == "check":
        h = input_hash(stage, stamps)
        CACHE.mkdir(parents=True, exist_ok=True)
        json.dump(mtimes(), open(CACHE / f"pre_{stage}.json", "w"))
        if os.environ.get("FORCE") or h is None or stamps.get(stage, {}).get("inputs") != h:
            sys.exit(1)
        if stage == "db_finish" and not DB.exists():
            sys.exit(1)
        sys.exit(0)
    if cmd == "save":
        pre = load(CACHE / f"pre_{stage}.json", {})
        now = mtimes()
        wrote = sorted(p for p, t in now.items() if pre.get(p) != t)
        old = set(stamps.get(stage, {}).get("outputs", []))
        outs = sorted(old | set(wrote))
        stamps[stage] = {"outputs": outs}
        stamps[stage]["inputs"] = input_hash(stage, stamps)
        if stage == "db_build":
            stamps["_db_build"] = stamps[stage]["inputs"]
        if stage == "db_finish":
            stamps["_db_version"] = hashlib.md5(((stamps.get("_db_build") or "") + stamps[stage]["inputs"]).encode()).hexdigest()
        json.dump(stamps, open(STAMPS, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
