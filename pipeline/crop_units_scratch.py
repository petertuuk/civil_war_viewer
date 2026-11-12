import json, os, sys, re, difflib, urllib.request
from PIL import Image
sys.path.insert(0, os.path.expanduser('~/mnt/civil_war_viewer/pipeline'))
import segment_dyers as S
H = os.path.expanduser('~')
targets = json.load(open(f'{H}/targets.json'))
U = {u['id']: u for u in map(json.loads, open(f'{H}/mnt/civil_war_viewer/data/dyers/units_clean.jsonl'))}
leaves = sorted({p + 6 for t in targets for p in range(U[t]['page_start'], U[t]['page_end'] + 1)})
pages = {}
for i, W, Hh, lines in S.read_pages(f'{H}/dy.xml'):
    if i in leaves: pages[i] = (W, Hh, lines)
    if i > max(leaves): break
norm = lambda s: re.findall(r'[a-z0-9]+', s.lower())
out = []
for t in targets:
    u = U[t]; want = norm(u['heading'] + ' ' + u['text_ocr'])
    for p in range(u['page_start'], u['page_end'] + 1):
        leaf = p + 6; W, Hh, lines = pages[leaf]
        img = f'{H}/img/n{leaf}.jpg'
        if not os.path.exists(img):
            open(img, 'wb').write(urllib.request.urlopen(urllib.request.Request(
                f'https://archive.org/download/08697590.3359.emory.edu/page/n{leaf}.jpg', headers={'User-Agent': 'CivilWarViewer/0.2'}), timeout=60).read())
        im = Image.open(img); sx, sy = im.width / W, im.height / Hh
        ws = set(want)
        hit = [ln for ln in lines if len(norm(ln[4])) and sum(w in ws for w in norm(ln[4])) / len(norm(ln[4])) >= 0.6 and len(norm(ln[4])) >= 2]
        if not hit: continue
        for col in (0, 1):
            hc = [ln for ln in hit if (ln[0] + ln[2]) / 2 >= W / 2] if col else [ln for ln in hit if (ln[0] + ln[2]) / 2 < W / 2]
            if not hc: continue
            l = min(x[0] for x in hc); r = max(x[2] for x in hc); top = min(x[1] for x in hc); bot = max(x[3] for x in hc)
            box = (max(0, int((l - 40) * sx)), max(0, int((top - 140) * sy)), min(im.width, int((r + 40) * sx)), min(im.height, int((bot + 60) * sy)))
            crop = im.crop(box)
            name = f"{H}/mnt/civil_war_viewer/data/witness/crops/{t.replace('/', '__')}_p{p}_c{col}.jpg"
            os.makedirs(os.path.dirname(name), exist_ok=True)
            crop.save(name, quality=90); out.append((t, p, col, crop.size, len(hc)))
for o in out: print(o)
