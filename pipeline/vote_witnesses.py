"""Clean Dyer's OCR text by word-level voting against hand-typed transcriptions.

usage: python pipeline/vote_witnesses.py data/dyers/units_fixed.jsonl data/witness/matches.json \
           data/nps_us/units.jsonl data/cwa/cwa_units.json data/dyers/units_clean.jsonl [unit_id ...]

Witnesses: the OCR (base, keeps Dyer's layout), NPS (public domain), Civil War Archive (CWA;
checking witness only: its words are used only where they agree with NPS or replace OCR junk).
Rules, per OCR span where a witness differs:
  - two witnesses agree on the same edit             -> take it (2 of 3)
  - a witness differs but the other agrees with OCR   -> keep OCR (2 of 3)
  - one witness only, or the two disagree:
      OCR span is junk (not a known word/number)      -> take the witness (prefer NPS; CWA only if NPS absent)
      a year outside 1861-1866 on one side             -> take the plausible side
      otherwise                                        -> keep OCR, record a flag
Output rows keep every input field; 'text' is the cleaned text, 'text_ocr' the original.
"""
import json, re, sys, os, collections, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
NOISE = re.compile(r"\s*(Source\s*-\s*\"?A Compendium.*|Predecessor units?\b.*)$", re.S | re.I)
def strip_noise(s):
    return NOISE.sub("", s) if s else s
ORD = re.compile(r"^\d+(st|nd|rd|th)$")

def toks(s):
    """Whitespace tokens; a punctuation-only token ('&', '—') rides on the word before it."""
    out = []
    for t in s.split():
        if not out: out.append(t); continue
        p = out[-1]
        if not norm(t) or re.search(r"\d-$", p) or \
                re.fullmatch(r"(?:.* )?[A-Z]\.", p) and re.fullmatch(r"[A-Z]\.[,;:.)]*", t):
            out[-1] += ' ' + t           # '&', '—'; '23- 27'; 'D. C.,' stay one token
        else: out.append(t)
    return out

def build_vocab(texts):
    c = collections.Counter(n for s in texts for t in s.split() if (n := norm(t)))
    return {w for w, k in c.items() if k >= 2}

def junk(tok, V):
    n = norm(tok)
    if not n: return True
    if n.isdigit() or ORD.match(n): return False
    if re.search(r"[^\w.,;:'\"()\-—–&/!?$]", tok): return True     # stray symbols: ° ^ « ♦ ...
    if re.search(r"\d", n): return True                              # 1S02, 18c4, l863
    return n not in V

YEARFIX = []
CONF = str.maketrans('sSbBlIiOoZzg', '885811100229')
def confusable(ospan, wspan):
    """OCR letters that are misread digits: 'S.' vs '8.', 'ii,' vs '11,'."""
    if len(ospan) != len(wspan): return False
    def fix(a):
        m = re.match(r"^(.*?)(st|nd|rd|th)?$", norm(a))
        return m.group(1).translate(CONF) + (m.group(2) or '')
    return all(norm(a) != norm(b) and (norm(b).isdigit() or ORD.match(norm(b))) and fix(a) == norm(b)
               or norm(a) == norm(b) for a, b in zip(ospan, wspan)) and any(norm(a) != norm(b) for a, b in zip(ospan, wspan))

def year_ok(n):
    return not (re.fullmatch(r"18\d\d", n) and not 1860 <= int(n) <= 1866)

def plausible(seq):
    return all(year_ok(norm(t)) for t in seq)

def proposals(o, w):
    """OCR-vs-witness edits keyed by OCR span; equal spans recorded as agreement."""
    sm = difflib.SequenceMatcher(None, [norm(t) for t in o], [norm(t) for t in w], autojunk=False)
    edits, agree, same = {}, [], {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            agree.append((i1, i2))
            for k in range(i2 - i1): same[i1 + k] = w[j1 + k]
        else: edits[(i1, i2)] = w[j1:j2]
    return edits, agree, same

def covered(span, agree):
    i1, i2 = span
    if i1 == i2:   # insertion point: witness agrees with OCR on both sides
        return any(a <= i1 - 1 < b for a, b in agree) and any(a <= i1 < b for a, b in agree)
    return any(a <= i1 and i2 <= b for a, b in agree)

def vote(ocr_text, nps_text, cwa_text, V, extra=None):
    o = toks(ocr_text)
    W = {k: toks(strip_noise(v)) for k, v in (('nps', nps_text), ('cwa', cwa_text)) if v}
    P = {k: proposals(o, w) for k, w in W.items()}
    decided, flags, st = {}, [], collections.Counter()
    spans = sorted({s for e, _, _ in P.values() for s in e}, key=lambda s: (s[0], s[1]))
    for span in spans:
        cand = {k: P[k][0][span] for k in P if span in P[k][0]}
        others = [k for k in P if k not in cand]
        ospan = o[span[0]:span[1]]
        ojunk = sum(junk(t, V) for t in ospan)
        same = len(cand) == 2 and [norm(t) for t in cand['nps']] == [norm(t) for t in cand['cwa']]
        if len(ospan) > 12 and all(len(c) * 2 < len(ospan) for c in cand.values()) and \
                not re.search(r"\b(?:REGIMENT|BATTALION|BATTERY|COMPANY)\b|\bOrganized at\b", ' '.join(ospan)):
            # a witness lacks a long stretch the OCR has: its copy stops short (the Civil War Archive's 7th
            # Maryland ends at May 1863), not OCR junk. Never cut text on a witness's silence, unless the stretch is
            # the next unit run on (a heading or 'Organized at' inside it).
            st['kept OCR (witnesses shorter)'] += 1; continue
        if same:
            decided[span] = cand['nps']; st['2 of 3'] += 1; continue
        if others and any(covered(span, P[k][1]) for k in others) and not (ospan and ojunk == len(ospan)):
            st['kept: other witness agrees with OCR'] += 1; continue
        pick = None
        joined = lambda seq: ''.join(norm(t) for t in seq)
        if ospan and any(joined(c) == joined(ospan) for c in cand.values()):
            st['kept OCR (spacing only)'] += 1; continue
        if ospan and plausible(ospan) and re.search(r"\b18\d\d\b", ' '.join(ospan)) and \
                all(not plausible(c) for c in cand.values()):
            st['kept OCR (witness year implausible)'] += 1; continue
        wy = {k: c for k, c in cand.items() if len(c) == 1 and re.fullmatch(r"186[0-6]", re.sub(r"\D", "", norm(c[0])) or "x")}
        oy = re.sub(r"\D", "", joined(ospan))
        if wy and 0 < len(ospan) <= 2 and not re.fullmatch(r"186[0-6]", oy) and 3 <= len(joined(ospan)) <= 6 \
                and not (len(wy) == 2 and len({norm(c[0]) for c in wy.values()}) == 2):
            k = 'nps' if 'nps' in wy else 'cwa'
            decided[span] = wy[k]; st['misread year fixed'] += 1
            YEARFIX.append((' '.join(ospan), ' '.join(wy[k]))); continue
        if ospan and ojunk * 2 >= len(ospan):
            pick = 'nps' if 'nps' in cand else 'cwa'; st['junk OCR replaced'] += 1
        elif not ospan and len(cand.get('nps', cand.get('cwa', []))) <= 12 and \
                (span[0] > 0 and junk(o[span[0]-1], V) or span[0] < len(o) and junk(o[span[0]], V)):
            pick = 'nps' if 'nps' in cand else 'cwa'; st['insertion next to junk'] += 1
        elif any(confusable(ospan, c) for c in cand.values()):
            pick = next(k for k in ('nps', 'cwa') if k in cand and confusable(ospan, cand[k])); st['misread digit fixed'] += 1
        elif not plausible(ospan) and any(plausible(c) for c in cand.values()):
            pick = next(k for k in ('nps', 'cwa') if k in cand and plausible(cand[k])); st['implausible year fixed'] += 1
        if pick:
            decided[span] = cand[pick]
        elif span[0] == 0 or not re.search(r"\d", ' '.join(ospan + [t for c in cand.values() for t in c])):
            st['kept OCR (word/style difference)'] += 1
        else:
            st['kept OCR (flagged: numbers)'] += 1
            flags.append({'ocr': ' '.join(ospan), **{k: ' '.join(v) for k, v in cand.items()},
                          'before': ' '.join(o[max(0, span[0] - 10):span[0]]), 'after': ' '.join(o[span[1]:span[1] + 10]),
                          '_span': span, '_cand': cand})
    # punctuation on words all sources agree on: OCR form unless it looks damaged
    ODD = re.compile(r"[_\"^°«»♦*~|\\]|['`](?=[\d\-]|$)|\d[\-'\"]$|^[\-'\"]")
    for i, t in enumerate(o):
        forms = [P[k][2][i] for k in ('nps', 'cwa') if k in P and i in P[k][2]]
        if not forms or forms[0] == t: continue
        if len(forms) == 2 and forms[0] == forms[1] or ODD.search(t) or \
                (forms[0].startswith(t) and re.fullmatch(r"[.,;:]+", forms[0][len(t):])):
            o[i] = forms[0]; st['punctuation repaired'] += 1
    decided.update(extra or {})
    # apply non-overlapping decisions left to right
    out, i = [], 0
    for (i1, i2) in sorted(decided):
        if i1 < i: continue
        out += o[i:i1] + decided[(i1, i2)]; i = i2
    out += o[i:]
    text = ' '.join(out)
    text = re.sub(r"\bService:\s*", "SERVICE.— ", text)       # NPS label -> Dyer's marker
    text = re.sub(r"\bSERVICE\s*[.,:]?\s*[-—–]+\s*", "SERVICE.— ", text)
    return text, st, flags

def record_problems(unit, text):
    """Lower is better: dates that run backwards or out of order, and losses that do not add up."""
    import extract_dyers as E
    claims = E.extract(dict(unit, text=text))
    bad, prev = 0, None
    for c in claims:
        if c["claim_type"] not in ("participated", "unit_at") or not c.get("date_start"):
            continue
        a, b = c["date_start"], c.get("date_end") or c["date_start"]
        if b < a: bad += 1
        if prev and a[:7] < prev[:7]: bad += 1
        prev = a
    for c in claims:
        if c["claim_type"] == "unit_numbers" and c.get("scope") == "whole_service":
            k, d, t = c.get("killed"), c.get("died_disease"), c.get("casualties_total")
            if None not in (k, d, t) and k + d != t: bad += 2
    return bad

DECISIONS = {}
# a decision with 'before' (human review, data/review) is keyed by the OCR words just before the span too, so two
# flags with the same reading in one unit (an empty insertion point) stay apart; older decisions by unit and reading
ctx_key = lambda b: ' '.join(norm(t) for t in (b or '').split()[-4:])

def resolve_flags(unit, nps, cwa, V, text, flags):
    """Try each witness reading of a flagged span; keep it only if the unit's record gets strictly better."""
    accepted, left, fixed = {}, [], collections.Counter()
    base = record_problems(unit, text)
    for f in flags:
        dec = DECISIONS.get((unit['id'], f['ocr'], ctx_key(f.get('before'))), DECISIONS.get((unit['id'], f['ocr'])))
        if dec is not None:                      # read off the page image (data/dyers/flag_decisions.jsonl)
            accepted[f['_span']] = dec.split()
            text, _, _ = vote(unit['text'], nps, cwa, V, extra=accepted)
            fixed['flag resolved from page image'] += 1
            continue
        best = None
        i1, i2 = f['_span']
        for k, toks_ in f['_cand'].items():
            # only like-for-like swaps of a few tokens: dropping text also drops its problems, so never reward it
            if not (0 < i2 - i1 <= 4 and toks_ and abs(len(toks_) - (i2 - i1)) <= 1): continue
            t2, _, _ = vote(unit['text'], nps, cwa, V, extra={**accepted, f['_span']: toks_})
            sc = record_problems(unit, t2)
            if sc < base and (best is None or sc < best[0]): best = (sc, k, toks_, t2)
        if best:
            accepted[f['_span']] = best[2]; base, text = best[0], best[3]
            fixed['flag resolved by date order / loss arithmetic'] += 1
        else:
            left.append(f)
    return text, left, fixed

def apply_overrides(rows, path, N, tot):
    """Hand-checked corrections from page images (data/dyers/unit_overrides.jsonl). Authoritative over the vote.
    ops: text (replace text, optional heading) | text_from_nps | new / new_from_nps (a unit the segmenter missed,
    placed after/before an existing id) | not_unit (a section title the segmenter took for a unit: dropped)."""
    if not path.exists():
        return rows
    import segment_dyers as SD
    by = {r['id']: r for r in rows}
    order = [r['id'] for r in rows]
    for line in open(path, encoding='utf-8'):
        if not line.strip(): continue
        o = json.loads(line); op = o['op']
        if op in ('text', 'text_from_nps'):
            r = by.get(o['id'])
            if not r: print('override: unknown id', o['id']); continue
            r['text'] = N[o['code']] if op == 'text_from_nps' else o['text']
            if o.get('heading'):
                r['heading'] = o['heading']; r.update(SD.parse_heading(o['heading']))
            r['override'] = o['source']; r['witnesses'] = sorted(set(r.get('witnesses', [])) | {'hand-checked'})
            r['ocr_quality'] = r.get('ocr_quality')
            tot['override: text'] += 1
        elif op in ('new', 'new_from_nps'):
            ref = o.get('after') or o.get('before')
            if ref not in by: print('override: unknown anchor', ref); continue
            base = by[ref]
            r = {'state': base['state'], 'heading': o['heading'], 'page_start': o['page'], 'page_end': o['page'],
                 'raw_text': '', 'text_ocr': '', 'text': N[o['code']] if op == 'new_from_nps' else o['text'],
                 'ocr_quality': None, 'id': o['id'], 'witnesses': ['hand-checked'], 'override': o['source'],
                 **SD.parse_heading(o['heading'])}
            by[r['id']] = r
            i = order.index(ref)
            order.insert(i + 1 if o.get('after') else i, r['id'])
            tot['override: new unit'] += 1
        elif op == 'not_unit':
            if o['id'] in by:
                order.remove(o['id']); del by[o['id']]; tot['override: not a unit (dropped)'] += 1
    return [by[i] for i in order]

def main(units_p, match_p, nps_p, cwa_p, out_p, *only):
    U = [json.loads(l) for l in open(units_p, encoding='utf-8')]
    M = json.load(open(match_p, encoding='utf-8'))
    N = {r['unit_code']: r['overview'] for r in map(json.loads, open(nps_p, encoding='utf-8'))}
    C = {(c['file'], c['anchor']): c['text'] for c in json.load(open(cwa_p, encoding='utf-8'))}
    V = build_vocab(list(N.values()) + list(C.values()))
    dp = Path(units_p).parent / 'flag_decisions.jsonl'
    if dp.exists():
        for l in open(dp, encoding='utf-8'):
            o = json.loads(l)
            if 'before' in o: DECISIONS[(o['unit_id'], o['ocr'], ctx_key(o['before']))] = o['printed']
            else: DECISIONS[(o['unit_id'], o['ocr'])] = o['printed']
    tot, rows, allflags = collections.Counter(), [], []
    for u in U:
        m = M.get(u['id'], {})
        if only and u['id'] not in only: continue
        nps = N.get(m['nps']['code']) if 'nps' in m else None
        cwa = C.get((m['cwa']['file'], m['cwa']['anchor'])) if 'cwa' in m else None
        r = dict(u, text_ocr=u.get('raw_text') if u.get('override') else u['text'], witnesses=sorted(k for k in m))
        if u.get('override'):                       # hand-checked text (fix_units.py): authoritative, no vote
            r['witnesses'] = sorted(set(r['witnesses']) | {'hand-checked'})
        elif nps or cwa:
            r['text'], st, fl = vote(u['text'], nps, cwa, V)
            if fl:
                r['text'], fl, fixed = resolve_flags(u, nps, cwa, V, r['text'], fl)
                st.update(fixed)
            r['clean_stats'] = dict(st); tot.update(st)
            for f in fl: allflags.append({'unit_id': u['id'], **{k: v for k, v in f.items() if not k.startswith('_')}})
        rows.append(r)
        tot[f"units with {len(r['witnesses'])} clean witness(es)"] += 1
    with open(out_p, 'w', encoding='utf-8') as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(Path(out_p).with_suffix('.flags.jsonl'), 'w', encoding='utf-8') as f:
        for r in allflags: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    for k, v in sorted(tot.items()): print(f"{k}: {v}")
    print(f"flags: {len(allflags)}")

if __name__ == '__main__':
    main(*sys.argv[1:])
