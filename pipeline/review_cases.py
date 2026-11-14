"""Cards for human review: cases the pipeline cannot settle, each with its evidence and a few answers.

usage: python pipeline/review_cases.py <djvu.xml> <dyers.pdf> data/review

Kinds (first version):
  ocr   Dyer's OCR, NPS and Civil War Archive disagree on a number (data/dyers/units_clean.flags.jsonl).
        Evidence: the printed lines cut from the page scan with the spot marked, the readings in context.
        Answer: what is printed -> data/dyers/flag_decisions.jsonl (vote_witnesses.py), via review_import.py.
        Flags at the very end of a unit (a witness running on into the next unit or an editor's note, or the
        OCR running into the next unit's heading) are segmentation questions, not readings: left out, listed in
        the report.
  year  A Dyer's stretch whose year a Wikidata match disputes but fix_years.py left alone because the shift
        breaks date order (data/dyers/fix_years_report.review.jsonl). Evidence: the stretch in Dyer's text,
        the matched event and its dates, the neighbours. Answer: shift / keep -> data/dyers/year_decisions.jsonl.

Writes data/review/cases.json (+ img/*.jpg) and cases_report.txt. Case ids are stable hashes of the case key, so
answers given earlier keep matching after a rebuild.
"""
import hashlib, json, re, subprocess, sys, os
import xml.etree.ElementTree as ET
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import segment_dyers as SD  # noqa: E402

norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
DPI = 150                      # render resolution (scan is 300 dpi)
IA = "https://archive.org/details/08697590.3359.emory.edu/page/n{}/mode/1up"


def cid(*key):
    return hashlib.sha1(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:12]


def read_pages(xml_path, keep):
    """{scan: (W, H, printed, [line: (l, t, r, b, [(word, l, t, r, b)])])} for scans whose printed page is in keep."""
    found, raw = {}, {}
    i = -1
    for _, el in ET.iterparse(xml_path, events=("end",)):
        if el.tag != "OBJECT":
            continue
        i += 1
        W, H = int(el.get("width")), int(el.get("height"))
        lines = []
        for line in el.iter("LINE"):
            ws = []
            for w in line.findall("WORD"):
                l, b, r, t = map(int, w.get("coords").split(",")[:4])
                if (w.text or "").strip():
                    ws.append(((w.text or "").strip(), l, t, r, b))
            if ws:
                lines.append((min(w[1] for w in ws), min(w[2] for w in ws), max(w[3] for w in ws),
                              max(w[4] for w in ws), ws))
        printed, body = SD.split_header(W, H, [(a, b, c, d, " ".join(x[0] for x in ws)) for a, b, c, d, ws in lines])
        found[i] = printed
        bodyset = {(a, b, c, d) for a, b, c, d, _ in body}
        raw[i] = (W, H, [ln for ln in lines if ln[:4] in bodyset])
        el.clear()
    printed_of, _ = SD.fix_page_numbers(found)
    out = {}
    for s, (W, H, lines) in raw.items():
        p = printed_of.get(s)
        if p in keep:
            out[s] = (W, H, p, order(W, lines))
    return out


def order(W, lines):
    """segment_dyers.reading_order on line tuples (bands split by full-width lines; left column, then right)."""
    mid = W / 2
    span = lambda ln: ln[0] < mid - 60 and ln[2] > mid + 60
    spanning = sorted([ln for ln in lines if span(ln)], key=lambda x: x[1])
    cols = [ln for ln in lines if not span(ln)]
    cuts = [s[1] for s in spanning] + [10 ** 9]
    out, prev = [], -1
    for k, cut in enumerate(cuts):
        band = [ln for ln in cols if prev <= ln[1] < cut]
        out += sorted([ln for ln in band if (ln[0] + ln[2]) / 2 < mid], key=lambda x: x[1])
        out += sorted([ln for ln in band if (ln[0] + ln[2]) / 2 >= mid], key=lambda x: x[1])
        if k < len(spanning):
            out.append(spanning[k])
        prev = cut
    return out


def locate(pages, scans, before, ocr, after):
    """Find before+ocr+after in the scans' words. Returns (scan, [words before], [words of the span], [words after])."""
    stream = []                    # (norm, scan, line_index, word)
    for s in scans:
        for li, ln in enumerate(pages[s][3]):
            for w in ln[4]:
                n = norm(SD.fix_ocr(w[0]))
                if n:
                    stream.append((n, s, li, w))
    qb = [n for t in before.split() if (n := norm(t))][-5:]
    qo = [n for t in ocr.split() if (n := norm(t))]
    qa = [n for t in after.split() if (n := norm(t))][:5]
    q = qb + qo + qa
    if not stream or len(q) < 3:
        return None
    sm = SequenceMatcher(None, [x[0] for x in stream], q, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
    if not blocks:
        return None
    # the cluster around the longest block: blocks whose stream offset agrees with it within 6 tokens
    main = max(blocks, key=lambda b: b.size)
    off = main.a - main.b
    blocks = [b for b in blocks if abs((b.a - b.b) - off) <= 6]
    if sum(b.size for b in blocks) < 0.5 * len(q):
        return None
    def at(j):                     # stream index for query index j (nearest block's offset)
        b = min(blocks, key=lambda b: 0 if b.b <= j < b.b + b.size else min(abs(j - b.b), abs(j - b.b - b.size + 1)))
        return max(0, min(len(stream) - 1, j + b.a - b.b))
    i0, i1 = at(len(qb)), at(len(qb) + len(qo) - 1) + 1 if qo else at(len(qb))
    ib, ia = at(0), at(len(q) - 1) + 1
    if not qo:                     # insertion point: between the last 'before' word and the first 'after' word
        i0 = i1 = at(len(qb) - 1) + 1 if qb else at(len(qb))
    return stream, ib, i0, i1, ia


def crop(pdf, pages, loc, out_jpg):
    """Cut the lines around the span from the scan, mark the span, save one image. A stretch that runs from one
    column (or page) into the next becomes one piece per column, stacked."""
    from PIL import Image, ImageDraw
    stream, ib, i0, i1, ia = loc
    k = i0 if i0 < len(stream) else i0 - 1
    f = DPI / 300
    side = lambda s, li: (lambda ln, W: 0 if ln[0] < W / 2 - 60 and ln[2] > W / 2 + 60 else 1 + ((ln[0] + ln[2]) / 2 >= W / 2))(pages[s][3][li], pages[s][0])
    groups = {}
    for x in stream[ib:ia] or [stream[k]]:
        groups.setdefault((x[1], side(x[1], x[2])), set()).add(x[2])
    hit = {id(z) for z in stream[i0:i1]}
    pieces = []
    for (s, col), lis in sorted(groups.items(), key=lambda g: (g[0][0], min(g[1]))):
        W, H, printed, lines = pages[s]
        same = [i for i in range(len(lines)) if side(s, i) == col]
        lo, hi = min(lis), max(lis)
        prev = [i for i in same if i < lo][-1:]; nxt = [i for i in same if i > hi][:1]
        rng = [i for i in same if (prev[0] if prev else lo) <= i <= (nxt[0] if nxt else hi)]
        box = [min(lines[i][0] for i in rng), min(lines[i][1] for i in rng),
               max(lines[i][2] for i in rng), max(lines[i][3] for i in rng)]
        box = [max(0, box[0] - 30), max(0, box[1] - 25), min(W, box[2] + 30), min(H, box[3] + 25)]
        x, y, w, h = int(box[0] * f), int(box[1] * f), int((box[2] - box[0]) * f), int((box[3] - box[1]) * f)
        tmp = str(out_jpg) + f".{len(pieces)}.tmp"
        subprocess.run(["pdftoppm", "-f", str(s + 1), "-l", str(s + 1), "-r", str(DPI), "-x", str(x), "-y", str(y),
                        "-W", str(w), "-H", str(h), "-gray", "-png", "-singlefile", pdf, tmp], check=True)
        im = Image.open(tmp + ".png").convert("RGBA"); os.remove(tmp + ".png")
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        tr = lambda X, Y: ((X * f) - x, (Y * f) - y)
        for z in stream[i0:i1]:
            if z[1] == s and side(s, z[2]) == col:
                _, wl, wt, wr, wb = z[3]
                d.rectangle([*tr(wl - 6, wt - 6), *tr(wr + 6, wb + 6)], fill=(255, 190, 0, 60), outline=(230, 110, 0, 255), width=2)
        if i0 == i1 and 0 < i0 <= len(stream):            # insertion: a caret after the previous word
            z = stream[i0 - 1]
            if z[1] == s and side(s, z[2]) == col:
                p = z[3]; X = p[3] + 8
                d.rectangle([*tr(X - 4, p[2] - 10), *tr(X + 4, p[4] + 10)], fill=(220, 60, 0, 230))
        pieces.append((Image.alpha_composite(im, ov).convert("RGB"), s, printed))
    gap = 14
    Wt = max(p[0].width for p in pieces); Ht = sum(p[0].height for p in pieces) + gap * (len(pieces) - 1)
    out = Image.new("RGB", (Wt, Ht), (255, 255, 255)); d = ImageDraw.Draw(out); yy = 0
    for n, (im, s, printed) in enumerate(pieces):
        if n:
            d.line([(0, yy - gap // 2), (Wt, yy - gap // 2)], fill=(150, 150, 150), width=1)
        out.paste(im, (0, yy)); yy += im.height + gap
    out.save(out_jpg, "JPEG", quality=78, optimize=True)
    s0 = stream[k][1]
    return s0, pages[s0][2]


def unit_title(u):
    st = (u.get("state") or "").title()
    h = re.sub(r"\s+", " ", u.get("heading") or "").strip(" .")
    h = re.sub(r"[A-Za-z]+", lambda m: m.group(0) if re.match(r"(st|nd|rd|th|and|of|the)$", m.group(0), re.I) and m.start() and h[m.start() - 1].isdigit() else
               (m.group(0).lower() if m.group(0).lower() in ("and", "of", "the") else m.group(0).capitalize()), h)
    return f"{st} {h}".strip()


def main(xml_path, pdf, out_dir):
    root = Path(".")
    out = Path(out_dir); (out / "img").mkdir(parents=True, exist_ok=True)
    units = {u["id"]: u for u in map(json.loads, open(root / "data/dyers/units_clean.jsonl", encoding="utf-8"))}
    flags = [json.loads(l) for l in open(root / "data/dyers/units_clean.flags.jsonl", encoding="utf-8")]
    years = [json.loads(l) for l in open(root / "data/dyers/fix_years_report.review.jsonl", encoding="utf-8")]
    cases, rep, skipped = [], [], []

    # ---------------- ocr
    keep_flags = []
    for f in flags:
        wit = {k: f[k] for k in ("nps", "cwa") if k in f}
        longest = max([len(f["ocr"].split())] + [len(v.split()) for v in wit.values()])
        if not f.get("after", "").strip() and longest > 3:
            skipped.append(f); continue
        keep_flags.append(f)
    need = set()
    for f in keep_flags:
        u = units[f["unit_id"]]
        need |= set(range(u["page_start"] - 1, u["page_end"] + 2))
    pages = read_pages(xml_path, need)
    scans_of = defaultdict(list)
    for s, (_, _, p, _) in pages.items():
        scans_of[p].append(s)
    nloc = 0
    for f in keep_flags:
        u = units[f["unit_id"]]
        scans = sorted(s for p in range(u["page_start"], u["page_end"] + 1) for s in scans_of.get(p, []))
        loc = locate(pages, scans, f["before"], f["ocr"], f["after"])
        key = ("ocr", f["unit_id"], f["ocr"], " ".join(f["before"].split()[-4:]))
        c = {"id": cid(*key), "kind": "ocr", "unit_id": f["unit_id"], "unit": unit_title(u),
             "before": f["before"], "after": f["after"], "ocr": f["ocr"], "page": u["page_start"]}
        if loc:
            img = out / "img" / f"{c['id']}.jpg"
            s, printed = crop(pdf, pages, loc, img)
            c.update(image=f"img/{c['id']}.jpg", page=printed, scan_url=IA.format(s)); nloc += 1
        elif scans:
            c["scan_url"] = IA.format(scans[0])
        readings, seen = [], set()
        for src, txt in (("OCR", f["ocr"]), ("NPS", f.get("nps")), ("Civil War Archive", f.get("cwa"))):
            if txt is None:
                continue
            n = norm(txt)
            if n in seen:
                for r in readings:
                    if norm(r["text"]) == n:
                        r["sources"].append(src)
                continue
            seen.add(n); readings.append({"text": txt, "sources": [src]})
        c["options"] = readings
        cases.append(c)
    rep.append(f"ocr flags: {len(flags)}; cards {len(keep_flags)} (scan crop found for {nloc}); "
               f"left out at the end of a unit (segmentation, not a reading): {len(skipped)}")
    rep += [f"  end of unit: {f['unit_id']} ocr={f['ocr'][:50]!r} " +
            " ".join(f"{k}={f[k][:50]!r}" for k in ("nps", "cwa") if k in f) for f in skipped]

    # ---------------- year
    for y in years:
        u = units.get(y["unit_id"], {})
        text = u.get("text", "")
        spans = [c["span"] for c in y["claims"] if c.get("span")]
        def find(sp, start=0):        # the claim's words in the text, punctuation between them free
            m = re.compile(r"\W+".join(map(re.escape, re.findall(r"\w+", sp)))).search(text, start)
            return (m.start(), m.end()) if m else (-1, -1)
        i0 = find(spans[0])[0] if spans else -1
        i1 = find(spans[-1], max(i0, 0))[1] if spans and i0 >= 0 else -1
        if i0 < 0 or i1 < 0:          # spans rebuilt by extract_dyers ('Duty there May 15'): the mentions' words
            ms = [c["mention"] for c in y["claims"] if c.get("mention")]
            i0 = find(ms[0])[0] if ms else -1
            j = find(ms[-1], max(i0, 0))[1] if ms and i0 >= 0 else -1
            i1 = text.find(".", j) if j >= 0 else -1
            i1 = i1 if i1 >= 0 else (j if j >= 0 else -1)
        if i0 >= 0 and i1 > i0:
            a = text.rfind(". ", 0, max(0, i0 - 220)); a = a + 2 if a >= 0 else 0
            b = text.find(". ", min(len(text), i1 + 200)); b = b + 1 if b >= 0 else len(text)
            ctx = [text[a:i0], text[i0:i1], text[i1:b]]
        else:
            ctx = ["", " ".join(spans), ""]
        y0 = int(y["date"][:4]); k = y["shift"]
        key = ("year", y["unit_id"], y["mention"], y["date"], k)
        cases.append({"id": cid(*key), "kind": "year", "unit_id": y["unit_id"], "unit": unit_title(u) or y["unit_id"],
                      "context": ctx, "year": y0, "to_year": y0 + k, "shift": k, "mention": y["mention"], "date": y["date"],
                      "why": y["why"], "before": y["before"], "after": y["after"],
                      "claims": y["claims"], "page": u.get("page_start")})
    rep.append(f"year cards: {len(years)}")
    cases.sort(key=lambda c: (c["kind"] != "ocr", c["unit_id"]))
    json.dump({"version": 1, "cases": cases}, open(out / "cases.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    open(out / "cases_report.txt", "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:1] + rep[-1:]))


if __name__ == "__main__":
    main(*sys.argv[1:])
