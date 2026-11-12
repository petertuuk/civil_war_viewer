import json, os, re, sys, urllib.request
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.expanduser('~/mnt/civil_war_viewer/pipeline'))
import segment_dyers as S
H = os.path.expanduser('~'); M = f'{H}/mnt/civil_war_viewer'
F = [json.loads(l) for l in open(f'{H}/vt/uc_test.flags.jsonl')]
U = {u['id']: u for u in map(json.loads, open(f'{H}/vt/uc_test.jsonl'))}
def kind(f):
    ws = [f[k] for k in ('nps', 'cwa') if k in f]; o = f['ocr']
    if not o or any(not w for w in ws): return 'lacks'
    if len(o.split()) > 4 or any(len(w.split()) > 4 for w in ws): return 'long'
    n = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    if {n(o)} | {n(w) for w in ws} <= {'ill', 'iii', 'ii1', 'i11', '111'}: return 'trivial'
    return 'num'
todo = [(i, f) for i, f in enumerate(F) if kind(f) == 'num']
print(len(todo), 'flags to crop')
norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
leaves = {}
for i, f in todo:
    u = U[f['unit_id']]
    for p in range(u['page_start'], (u['page_end'] or u['page_start']) + 1): leaves.setdefault(p + 6, []).append(i)
pages = {}
for li, W, Hh, lines in S.read_pages(f'{H}/dy.xml'):
    if li in leaves: pages[li] = (W, Hh, lines)
    if li > max(leaves): break
found = {}
for li, idxs in leaves.items():
    W, Hh, lines = pages[li]
    for i in idxs:
        if i in found: continue
        f = F[i]; target = norm(f['ocr'])
        for (l, t, r, b, tx) in lines:
            words = tx.split()
            for k in range(len(words)):
                for m in (1, 2, 3):
                    if norm(''.join(words[k:k+m])) == target and target:
                        pre = len(' '.join(words[:k])) + (1 if k else 0); span = len(' '.join(words[k:k+m])); L = max(1, len(tx)); found[i] = (li, (l, t, r, b), W, Hh, (l + (r - l) * pre / L, l + (r - l) * (pre + span) / L)); break
                if i in found: break
            if i in found: break
print('located', len(found))
os.makedirs(f'{M}/data/witness/flagcrops', exist_ok=True)
need = sorted({v[0] for v in found.values()})
from concurrent.futures import ThreadPoolExecutor
import time
def dl(li):
    img = f'{H}/img/n{li}.jpg'
    if os.path.exists(img) and os.path.getsize(img) > 10000: return 'have'
    for a in range(3):
        try:
            open(img, 'wb').write(urllib.request.urlopen(urllib.request.Request(
                f'https://archive.org/download/08697590.3359.emory.edu/page/n{li}.jpg', headers={'User-Agent': 'CivilWarViewer/0.2'}), timeout=60).read()); return 'ok'
        except Exception: time.sleep(2)
    return 'fail'
t0 = time.time()
with ThreadPoolExecutor(8) as ex: res = list(ex.map(dl, need))
print('pages', len(need), {k: res.count(k) for k in set(res)}, round(time.time() - t0), 's')
if 'fail' in res or (len(sys.argv) > 1 and sys.argv[1] == 'dl'): sys.exit()
crops = []
for i, (li, (l, t, r, b), W, Hh, (wx0, wx1)) in sorted(found.items()):
    img = f'{H}/img/n{li}.jpg'
    if not os.path.exists(img):
        open(img, 'wb').write(urllib.request.urlopen(urllib.request.Request(
            f'https://archive.org/download/08697590.3359.emory.edu/page/n{li}.jpg', headers={'User-Agent': 'CivilWarViewer/0.2'}), timeout=60).read())
    im = Image.open(img); sx, sy = im.width / W, im.height / Hh
    x0, y0 = max(0, int((l - 30) * sx)), max(0, int((t - 45) * sy))
    c = im.crop((x0, y0, min(im.width, int((r + 30) * sx)), min(im.height, int((b + 45) * sy)))).convert('RGB')
    ImageDraw.Draw(c).rectangle((int(wx0 * sx) - x0 - 6, int(t * sy) - y0 - 4, int(wx1 * sx) - x0 + 6, int(b * sy) - y0 + 4), outline='red', width=4)
    c = c.resize((1100, max(1, int(c.height * 1100 / c.width))))
    crops.append((i, c))
sheets = []
from PIL import ImageFont
FNT = ImageFont.load_default(size=30)
for s in range(0, len(crops), 6):
    part = crops[s:s+6]; h = sum(c.height + 50 for _, c in part)
    sheet = Image.new('RGB', (1100, h), 'white'); d = ImageDraw.Draw(sheet); y = 0
    for i, c in part:
        f = F[i]; d.text((4, y + 6), f"#{i}  OCR: {f['ocr']}   NPS: {f.get('nps','-')}   CWA: {f.get('cwa','-')}", fill='blue', font=FNT)
        sheet.paste(c, (0, y + 46)); y += c.height + 50
    name = f'{M}/data/witness/flagcrops/sheet{s//6:02d}.jpg'; sheet.save(name, quality=85); sheets.append(name)
print(len(sheets), 'sheets'); json.dump({'located': sorted(found), 'todo': [i for i, _ in todo]}, open(f'{M}/data/witness/flagcrops/index.json', 'w'))
