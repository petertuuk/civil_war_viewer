"""Work in a local copy of the project; write back only what changed.

The project folder is reached through the desktop app's file bridge, which moves about 1.5 MB/s either way (measured
2026-11-12: 50 MB written in 33-45 s; an old hard drive does 80+ MB/s, so the bridge, not the disk, is the limit). A
rebuild that writes its outputs straight into the folder spends most of its time waiting, runs past the shell's
~170 s per call, and a call cut off mid-write leaves a truncated file behind (claims_wikipedia.jsonl, 2026-11-12).

    python3 pipeline/workcopy.py pull  [--to ~/work/cwv] [--force]   copy the working set to local disk (resumable:
                                                           repeat until it says "complete"; ~6 min the first time);
                                                           mirrors moves and removals; refuses while local changes are
                                                           unpushed, unless --force
    (cd ~/work/cwv && bash pipeline/rebuild.sh events ...)  run stages locally (seconds of I/O, not minutes)
    python3 pipeline/workcopy.py status                   what changed locally
    python3 pipeline/workcopy.py push  [--db] [--force] [path ...]   write changed files back (all, or those under
                                                          the paths given), each to a temporary name then renamed
                                                          over the old one (never half-written); JSON / JSONL files
                                                          that do not parse are refused; resumable like pull

The working set is the project minus raw material the stages do not read (EXCLUDE). pull records each file's md5,
size and mtime in <work>/.workcopy_manifest.json; push sends a file when its md5 differs from that record and skips it
(reported as a conflict) when the project copy changed since the pull, unless --force. *.db files go back only with
--db (civil_war.db is rebuilt by the db stage; ~130 MB is ~90 s through the bridge).
"""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path

PROJECT = Path(os.path.expanduser(os.environ.get("CWV_PROJECT", "~/mnt/civil_war_viewer")))   # the bridged folder
DEFAULT_WORK = Path.home() / "work" / "cwv"
INCLUDE = ["pipeline", "viewer", "data", "README.md", ".gitignore"]
EXCLUDE = ["__pycache__", "*.pyc", "_to_delete", "_archive", "sources", "data/nps/html", "data/witness/pages", "data/witness/crops",
           "data/witness/flagcrops", "data/external/naturalearth", "data/_before_v2", "data/wikidata/raw",
           "data/wikidata/raw_old", "data/cwa/cwa_pages.tgz", "data/dyers/claims_rules_ocr_v1.jsonl",
           "data/dyers/claims_rules_before_gold_fixes.jsonl", ".workcopy_manifest.json", ".rebuild_stamps.json"]
BUDGET = 120          # seconds per call, under the shell's limit


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def excluded(rel):
    import fnmatch
    parts = rel.split("/")
    for e in EXCLUDE:
        if "/" in e:
            if rel == e or rel.startswith(e + "/"):
                return True
        elif any(fnmatch.fnmatch(x, e) for x in parts):
            return True
    return False


def local_files(work):
    for root, ds, fs in os.walk(work):
        ds[:] = [d for d in ds if not excluded(os.path.relpath(os.path.join(root, d), work))]
        for f in fs:
            rel = os.path.relpath(os.path.join(root, f), work)
            if not excluded(rel):
                yield rel


def pull(work, force=False):
    work.mkdir(parents=True, exist_ok=True)
    if (work / ".workcopy_manifest.json").exists() and not force:
        _, ch = changed(work)
        if ch:
            print(f"pull: {len(ch)} local changes not pushed (status lists them); push them or pull --force"); sys.exit(1)
    # --delete: files moved or removed in the project go from the local copy too
    args = ["rsync", "-a", "--partial", "--relative", "--delete", "--exclude=.workcopy_manifest.json"] + [f"--exclude={e}" for e in EXCLUDE] + \
           [f"./{i}" for i in INCLUDE if (PROJECT / i).exists()] + [str(work) + "/"]
    try:
        r = subprocess.run(args, cwd=PROJECT, timeout=BUDGET)
    except subprocess.TimeoutExpired:
        print("pull: not complete yet (time budget); run pull again"); return
    if r.returncode != 0:
        print("pull: rsync failed, rc", r.returncode); sys.exit(1)
    man = {}
    for rel in local_files(work):
        st = os.stat(work / rel)
        man[rel] = {"md5": md5(work / rel), "size": st.st_size, "mtime": int(st.st_mtime)}
    json.dump(man, open(work / ".workcopy_manifest.json", "w"))
    print(f"pull: complete, {len(man)} files in {work}; run stages there: cd {work} && bash pipeline/rebuild.sh <stage>")


def changed(work):
    man = json.load(open(work / ".workcopy_manifest.json"))
    out = []
    for rel in local_files(work):
        m = man.get(rel)
        if m is None or os.path.getsize(work / rel) != m["size"] or md5(work / rel) != m["md5"]:
            out.append(rel)
    return man, sorted(out)


def valid(p):
    if p.suffix == ".json":
        try:
            json.load(open(p, encoding="utf-8")); return True
        except Exception:
            return False
    if p.suffix == ".jsonl":
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        json.loads(line)
                    except Exception:
                        return False
    return True


def push(work, with_db=False, force=False, only=None):
    man, ch = changed(work)
    t0, done, skipped = time.time(), 0, []
    todo = [r for r in ch if (with_db or not r.endswith(".db")) and (not only or any(r == o or r.startswith(o.rstrip("/") + "/") for o in only))]
    for rel in todo:
        if time.time() - t0 > BUDGET - 20:
            print(f"push: time budget used; {len(todo) - done - len(skipped)} files left, run push again"); break
        src, dst = work / rel, PROJECT / rel
        m = man.get(rel)
        if dst.exists() and m and not force:
            st = os.stat(dst)
            if st.st_size != m["size"] or abs(int(st.st_mtime) - m["mtime"]) > 2:
                skipped.append(rel); print("  conflict (project copy changed since pull), skipped:", rel); continue
        if not valid(src):
            skipped.append(rel); print("  does not parse, NOT pushed:", rel); continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".workcopy_tmp")
        subprocess.run(["cp", "--preserve=timestamps", str(src), str(tmp)], check=True)
        os.replace(tmp, dst)
        st = os.stat(src)
        man[rel] = {"md5": md5(src), "size": st.st_size, "mtime": int(os.stat(dst).st_mtime)}
        done += 1
        print(f"  pushed {rel} ({st.st_size // 1000} kB)")
    json.dump(man, open(work / ".workcopy_manifest.json", "w"))
    left = [r for r in changed(work)[1] if (with_db or not r.endswith(".db")) and r not in skipped
            and (not only or any(r == o or r.startswith(o.rstrip("/") + "/") for o in only))]
    print(f"push: {done} written, {len(skipped)} skipped" + ("; complete" if not left else f"; {len(left)} still to push"))


def main(argv):
    if not argv or argv[0] not in ("pull", "push", "status"):
        print(__doc__); sys.exit(2)
    work = Path(os.path.expanduser(argv[argv.index("--to") + 1])) if "--to" in argv else DEFAULT_WORK
    if argv[0] == "pull":
        pull(work, "--force" in argv)
    elif argv[0] == "status":
        _, ch = changed(work)
        print(f"{len(ch)} changed locally:"); print("\n".join("  " + c for c in ch))
    else:
        only = [a for a in argv[1:] if not a.startswith("--") and (argv.index(a) == 0 or argv[argv.index(a) - 1] != "--to")]
        push(work, "--db" in argv, "--force" in argv, only)


if __name__ == "__main__":
    main(sys.argv[1:])
