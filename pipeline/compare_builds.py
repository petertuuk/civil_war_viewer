"""Compare two builds of the project: prove a refactor changed nothing, or show exactly what a change moved.

    python3 pipeline/compare_builds.py <reference dir> <new dir> [--files-only | --db-only] [--only PREFIX ...] [--max N]

Both directories are project-shaped (data/, viewer/war/data/, civil_war.db). Exit status 0 only when everything compared is identical.

Files: every file under data/ and viewer/war/data/ is compared by md5, except data/external/ (downloaded sources), data/review/img/
(card images), caches (__pycache__, *.workcopy_tmp) and the stamp files. Printed: files only in the reference, only in the new
build, and different; for a different .jsonl also both line counts and the first N differing lines.

Database: civil_war.db is never byte-identical between two builds (build_db.py and brigade_inference.py stamp the current time), so it is
compared by content: for every table, all rows in primary-key order, leaving out the time-stamp columns in TIMESTAMP_COLUMNS. Printed per table:
identical, or the number of differing rows with the first N. A column that exists on one side only is reported as a schema difference.
"""
import hashlib, json, os, sqlite3, sys
from itertools import zip_longest

FILE_ROOTS = ["data", "viewer/war/data"]
SKIP_DIRS = {"__pycache__", "external", "img"}          # data/external (downloads) and data/review/img (card images)
SKIP_PATHS = ("data/external/", "data/review/img/")
SKIP_FILES = {".workcopy_manifest.json", ".rebuild_stamps.json"}
SKIP_SUFFIX = (".workcopy_tmp", ".pyc", ".tmp")
TIMESTAMP_COLUMNS = {("claim", "extracted_at"), ("source", "fetched_at"), ("override", "created_at")}


def walk(root, roots):
    out = {}
    for r in roots:
        base = os.path.join(root, r)
        for dp, ds, fs in os.walk(base):
            rel_dir = os.path.relpath(dp, root).replace(os.sep, "/")
            ds[:] = [d for d in ds if d != "__pycache__" and (rel_dir + "/" + d + "/") not in SKIP_PATHS]
            for f in fs:
                if f in SKIP_FILES or f.endswith(SKIP_SUFFIX):
                    continue
                out[rel_dir + "/" + f] = os.path.join(dp, f)
    return out


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def line_diff(a, b, n):
    """(lines in a, lines in b, first n differing (line number, a-line, b-line)) for two text files."""
    na = nb = 0
    first = []
    with open(a, encoding="utf-8", errors="replace") as fa, open(b, encoding="utf-8", errors="replace") as fb:
        for i, (x, y) in enumerate(zip_longest(fa, fb), 1):
            na += x is not None
            nb += y is not None
            if x != y and len(first) < n:
                x, y = (x or "").rstrip("\n"), (y or "").rstrip("\n")
                k = next((j for j, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))   # first differing character
                lo = max(0, k - 60)
                first.append((i, f"{'...' if lo else ''}{x[lo:k + 140]}", f"{'...' if lo else ''}{y[lo:k + 140]}"))
    return na, nb, first


def compare_files(ref, new, only, n):
    A, B = walk(ref, FILE_ROOTS), walk(new, FILE_ROOTS)
    if only:
        A = {k: v for k, v in A.items() if k.startswith(tuple(only))}
        B = {k: v for k, v in B.items() if k.startswith(tuple(only))}
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    diff = []
    for k in sorted(set(A) & set(B)):
        if os.path.getsize(A[k]) != os.path.getsize(B[k]) or md5(A[k]) != md5(B[k]):
            diff.append(k)
    print(f"files compared: {len(set(A) & set(B))}; only in reference {len(only_a)}; only in new {len(only_b)}; different {len(diff)}")
    for k in only_a[:50]:
        print("  only in reference:", k)
    for k in only_b[:50]:
        print("  only in new:", k)
    for k in diff:
        print("  different:", k)
        if k.endswith(".jsonl") or k.endswith(".csv") or k.endswith(".psv") or k.endswith(".txt") or k.endswith(".tsv"):
            na, nb, first = line_diff(A[k], B[k], n)
            print(f"    lines {na} -> {nb}")
            for i, x, y in first:
                print(f"    line {i}:\n      ref: {x}\n      new: {y}")
    return not (only_a or only_b or diff)


def tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def columns(con, t):
    info = con.execute(f'PRAGMA table_info("{t}")').fetchall()      # cid, name, type, notnull, dflt, pk
    cols = [r[1] for r in info]
    pk = [r[1] for _, r in sorted((r[5], r) for r in info if r[5])]
    return cols, pk


def compare_db(ref, new, n):
    pa, pb = os.path.join(ref, "civil_war.db"), os.path.join(new, "civil_war.db")
    for p in (pa, pb):
        if not os.path.exists(p):
            print("database missing:", p)
            return False
    A = sqlite3.connect(f"file:{pa}?mode=ro", uri=True)
    B = sqlite3.connect(f"file:{pb}?mode=ro", uri=True)
    ta, tb = tables(A), tables(B)
    ok = True
    for t in sorted(set(ta) ^ set(tb)):
        print(f"  table only on one side: {t} ({'reference' if t in ta else 'new'})")
        ok = False
    for t in sorted(set(ta) & set(tb)):
        ca, pka = columns(A, t)
        cb, pkb = columns(B, t)
        if ca != cb:
            print(f"  {t}: schema differs; reference {ca}; new {cb}")
            ok = False
            continue
        keep = [c for c in ca if (t, c) not in TIMESTAMP_COLUMNS]
        order = ", ".join(f'"{c}"' for c in (pka or ["rowid"]))
        sel = ", ".join(f'"{c}"' for c in keep)
        qa = A.execute(f'SELECT {sel} FROM "{t}" ORDER BY {order}')
        qb = B.execute(f'SELECT {sel} FROM "{t}" ORDER BY {order}')
        rows = bad = 0
        first = []
        for x, y in zip_longest(qa, qb):
            rows += 1
            if x != y:
                bad += 1
                if len(first) < n:
                    first.append((x, y))
        if bad:
            ok = False
            print(f"  {t}: {bad} of {rows} rows differ")
            for x, y in first:
                print(f"    ref: {str(x)[:220]}\n    new: {str(y)[:220]}")
        else:
            print(f"  {t}: identical ({rows} rows)")
    return ok


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    n = 5
    only = []
    if "--max" in argv:
        n = int(argv[argv.index("--max") + 1])
    if "--only" in argv:
        i = argv.index("--only") + 1
        while i < len(argv) and not argv[i].startswith("--"):
            only.append(argv[i]); i += 1
    args = [a for a in args if a not in only and a != str(n)]
    if len(args) != 2:
        print(__doc__); return 2
    ref, new = args
    ok = True
    if "--db-only" not in argv:
        print("== files")
        ok &= compare_files(ref, new, only, n)
    if "--files-only" not in argv:
        print("== database (time stamps left out)")
        ok &= compare_db(ref, new, n)
    print("IDENTICAL" if ok else "DIFFERENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
