"""Match each Dyer's unit to its clean transcriptions (NPS page, Civil War Archive entry) by content.

usage: python pipeline/match_witnesses.py data/dyers/units.jsonl data/nps_us/units.jsonl \
           data/scores/dyer_to_nps.csv data/cwa/cwa_units.json data/witness/matches.json
Heading/code links propose candidates; word-bigram overlap with the OCR text decides.
CWA is a checking witness only (site claims copyright): store pointers, not text.
"""
import csv, json, re, sys, collections
from pathlib import Path

ST = {'al':'ALABAMA','ar':'ARKANSAS','ca':'CALIFORNIA','co':'COLORADO','ct':'CONNECTICUT','dc':'DISTRICT OF COLUMBIA',
      'de':'DELAWARE','fl':'FLORIDA','ga':'GEORGIA','ia':'IOWA','il':'ILLINOIS','in':'INDIANA','ks':'KANSAS',
      'ky':'KENTUCKY','la':'LOUISIANA','ma':'MASSACHUSETTS','md':'MARYLAND','me':'MAINE','mi':'MICHIGAN','mn':'MINNESOTA',
      'mo':'MISSOURI','ms':'MISSISSIPPI','nc':'NORTH CAROLINA','ne':'NEBRASKA','nh':'NEW HAMPSHIRE','nj':'NEW JERSEY',
      'nm':'NEW MEXICO','nv':'NEVADA','ny':'NEW YORK','oh':'OHIO','or':'OREGON','pa':'PENNSYLVANIA','ri':'RHODE ISLAND',
      'sc':'SOUTH CAROLINA','tn':'TENNESSEE','tx':'TEXAS','va':'VIRGINIA','vt':'VERMONT','wa':'WASHINGTON TERRITORY',
      'wi':'WISCONSIN','wv':'WEST VIRGINIA','rg':'U.S. REGULAR ARMY','vetres':'U.S. VETERAN RESERVE CORPS',
      'vetvol':'U.S. VETERAN VOLUNTEERS','usvol':'U.S. VOLUNTEERS'}
STOP = {'regiment', 'independent', 'company', 'battery', 'the', 'of'}

def cwa_state(f):
    if f.startswith('Unreghst_uscol'): return 'U.S. COLORED TROOPS'
    if f.startswith('Unreghst_deafriq'): return "CORPS D'AFRIQUE"
    if f.startswith('Unreghst_dt'): return 'DAKOTA TERRITORY'
    m = re.match(r'Unreghst_un(vetres|vetvol|usvol|rg|ind|[a-z]{2})', f)
    return ({'ind': 'INDIAN TERRITORY'}.get(m.group(1)) or ST.get(m.group(1))) if m else None

words = lambda s: re.findall(r"[a-z0-9]+", s.lower())
key = lambda h: ' '.join(x for x in words(h) if x not in STOP)
def grams(s):
    w = words(s); return set(zip(w, w[1:])) if len(w) > 1 else set((x,) for x in w)
def overlap(a, b):  # share of the smaller text's bigrams found in the other
    return len(a & b) / max(1, min(len(a), len(b)))
OCRD = str.maketrans({'S': '8', 's': '8', 'B': '8', 'l': '1', 'I': '1', 'i': '1', 'O': '0', 'o': '0', 'Z': '2', 'z': '2'})
SUF = lambda n: 'th' if n % 100 in (11, 12, 13) else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
def ordinal(h):
    """First ordinal in a heading, OCR-repaired; None if absent or not trustworthy (e.g. '5-nd')."""
    m = re.search(r"\b([0-9SsBlIiOoZz]{1,3})[- ]?(st|nd|rd|th)\b", h, re.I)
    if not m or not re.search(r"\d", m.group(1)) and m.group(1) not in ('S', 's'): return None
    d = m.group(1).translate(OCRD)
    if not d.isdigit(): return None
    n = int(d)
    return n if SUF(n) == m.group(2).lower() else None
def lenok(a, b):
    la, lb = len(a), len(b)
    return min(la, lb) / max(1, la, lb)

def main(units_p, nps_p, links_p, cwa_p, out_p):
    U = [json.loads(l) for l in open(units_p, encoding='utf-8')]
    N = {r['unit_code']: r for r in map(json.loads, open(nps_p, encoding='utf-8')) if not r['empty']}
    L = {l['unit_id']: l for l in csv.DictReader(open(links_p, encoding='utf-8'))}
    C = json.load(open(cwa_p, encoding='utf-8'))
    bystate = collections.defaultdict(list)
    for i, c in enumerate(C):
        st = cwa_state(c['file'])
        if st and len(c['text'].split()) > 2:
            bystate[st].append((i, key(c['heading']), grams(c['text']), c))
    ng = {k: grams(v['overview']) for k, v in N.items()}
    # Score every plausible pairing, then assign greedily (best first), one witness entry per unit.
    out, st = {u['id']: {} for u in U}, collections.Counter()
    pairs_c, pairs_n = [], []
    for u in U:
        g, k, on = grams(u['text']), key(u['heading']), ordinal(u['heading'])
        short = len(u['text'].split()) < 25
        for i, ck, cg, c in bystate.get(u['state'], []):
            co = ordinal(c['heading'])
            if on is not None and co is not None and on != co: continue
            s = overlap(g, cg) * lenok(g, cg) ** 0.5 + (0.25 if ck == k else 0)
            if s >= 0.45 or (ck == k and short and s >= 0.25):
                pairs_c.append((s, u['id'], i, c))
    used = set()
    for s, uid, i, c in sorted(pairs_c, key=lambda x: -x[0]):
        if 'cwa' in out[uid] or i in used: continue
        used.add(i); out[uid]['cwa'] = {'file': c['file'], 'anchor': c['anchor'], 'heading': c['heading'], 'score': round(s, 3)}
    # NPS: content check against the OCR, or against the unit's CWA text when the OCR is too garbled to judge
    cwa_text = {(c['file'], c['anchor']): c['text'] for c in C}
    for u in U:
        l = L.get(u['id'])
        if not l: continue
        g, short = grams(u['text']), len(u['text'].split()) < 25
        cw = out[u['id']].get('cwa'); cg = grams(cwa_text[(cw['file'], cw['anchor'])]) if cw else None
        cands = [l['unit_code']] if l['status'] == 'linked' else [x for x in l['candidates'].split('|') if x]
        for code in cands:
            if code not in N: continue
            s1 = overlap(g, ng[code]) * lenok(g, ng[code]) ** 0.5
            s2 = overlap(cg, ng[code]) * lenok(cg, ng[code]) ** 0.5 if cg else 0
            sc = max(s1, s2)
            if len(g) >= 20 and overlap(g, ng[code]) >= 0.8:   # whole Dyer's text inside a longer NPS page
                sc = max(sc, 0.8)                             # (NPS appends predecessor units' histories)
            if sc >= 0.4 or (short and sc >= 0.2):
                pairs_n.append((sc, u['id'], code, l['status'] + (' (via CWA)' if s2 > s1 and s1 < 0.4 else '')))
            else:
                st['nps rejected (' + l['status'] + ')'] += 1
    used = set()
    for s, uid, code, status in sorted(pairs_n, key=lambda x: -x[0]):
        if 'nps' in out[uid] or code in used: continue
        used.add(code); out[uid]['nps'] = {'code': code, 'score': round(s, 3), 'link': status}
    for rec in out.values():
        st[f"witnesses {len(rec)}"] += 1
        for w_ in rec: st[w_ + ' matched'] += 1
    Path(out_p).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(out_p, 'w', encoding='utf-8'), indent=0)
    for k2, v in sorted(st.items()): print(f"{k2}: {v}")

if __name__ == '__main__':
    main(*sys.argv[1:6])
