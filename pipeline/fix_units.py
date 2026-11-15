"""Apply hand-checked unit corrections to the segmented Dyer's units, before linking, matching and voting.

usage: python pipeline/fix_units.py data/dyers/units.jsonl data/dyers/unit_overrides.jsonl \
           data/nps_us/units.jsonl data/dyers/units_fixed.jsonl

Override ops (one JSON object per line in unit_overrides.jsonl; every row names its source):
  text            replace a unit's text (and optionally its heading); the text is hand-checked: the vote keeps it
                  ("text" may be omitted to change only the heading, in which case the text still goes to the vote)
  text_from_nps   take the unit's text from an NPS page ("code"); public domain Dyer's text
  new / new_from_nps   a unit the segmenter missed, placed "after" or "before" an existing id
  not_unit        a section title or fragment the segmenter took for a unit: dropped
  set_state       move a run of units (ids_from..ids_to, inclusive) to another section ("state")
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cwv import paths  # noqa: E402
import segment_dyers as SD


def main(units_p, over_p, nps_p, out_p):
    rows = [json.loads(l) for l in open(units_p, encoding='utf-8')]
    N = {r['unit_code']: r['overview'] for r in map(json.loads, open(nps_p, encoding='utf-8'))}
    by = {r['id']: r for r in rows}
    order = [r['id'] for r in rows]
    st = {}
    for line in open(over_p, encoding='utf-8'):
        if not line.strip(): continue
        o = json.loads(line); op = o['op']
        st[op] = st.get(op, 0) + 1
        if op in ('text', 'text_from_nps'):
            r = by.get(o['id'])
            if not r: print('override: unknown id', o['id']); continue
            if op == 'text_from_nps' or 'text' in o:
                r['text'] = N[o['code']] if op == 'text_from_nps' else o['text']
                r['override'] = o['source']
            if o.get('heading'):
                r['heading'] = o['heading']; r.update(SD.parse_heading(o['heading']))
                r.setdefault('override_heading', o['source'])
        elif op in ('new', 'new_from_nps'):
            ref = o.get('after') or o.get('before')
            if ref not in by: print('override: unknown anchor', ref); continue
            r = {'state': by[ref]['state'], 'heading': o['heading'], 'page_start': o['page'], 'page_end': o['page'],
                 'raw_text': '', 'text': N[o['code']] if op == 'new_from_nps' else o['text'],
                 'ocr_quality': None, 'id': o['id'], 'override': o['source'], **SD.parse_heading(o['heading'])}
            by[r['id']] = r
            i = order.index(ref)
            order.insert(i + 1 if o.get('after') else i, r['id'])
        elif op == 'not_unit':
            if o['id'] in by:
                order.remove(o['id']); del by[o['id']]
            else:
                print('override: unknown id', o['id'])
        elif op == 'set_state':
            if o['ids_from'] not in order or o['ids_to'] not in order:
                print('override: unknown range', o['ids_from'], o['ids_to']); continue
            for i in order[order.index(o['ids_from']):order.index(o['ids_to']) + 1]:
                by[i]['state'] = o['state']; by[i]['override_state'] = o['source']
    out = [by[i] for i in order]
    with open(out_p, 'w', encoding='utf-8') as f:
        for r in out: f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"units {len(rows)} -> {len(out)}; ops {st}")


if __name__ == '__main__':
    main(*(sys.argv[1:5] or paths.defaults("fix_units")))
