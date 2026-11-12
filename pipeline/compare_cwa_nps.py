import json,csv,re,difflib,collections,os,sys
H=os.path.expanduser('~/cwa/')
ST={'al':'ALABAMA','ar':'ARKANSAS','ca':'CALIFORNIA','co':'COLORADO','ct':'CONNECTICUT','dc':'DISTRICT OF COLUMBIA','de':'DELAWARE','dt':'DAKOTA TERRITORY','fl':'FLORIDA','ga':'GEORGIA','ia':'IOWA','il':'ILLINOIS','in':'INDIANA','ks':'KANSAS','ky':'KENTUCKY','la':'LOUISIANA','ma':'MASSACHUSETTS','md':'MARYLAND','me':'MAINE','mi':'MICHIGAN','mn':'MINNESOTA','mo':'MISSOURI','ms':'MISSISSIPPI','nc':'NORTH CAROLINA','ne':'NEBRASKA','nh':'NEW HAMPSHIRE','nj':'NEW JERSEY','nm':'NEW MEXICO','nv':'NEVADA','ny':'NEW YORK','oh':'OHIO','or':'OREGON','pa':'PENNSYLVANIA','ri':'RHODE ISLAND','sc':'SOUTH CAROLINA','tn':'TENNESSEE','tx':'TEXAS','va':'VIRGINIA','vt':'VERMONT','wa':'WASHINGTON TERRITORY','wi':'WISCONSIN','wv':'WEST VIRGINIA','rg':'U.S. REGULAR ARMY','vetres':'U.S. VETERAN RESERVE CORPS','vetvol':'U.S. VETERAN VOLUNTEERS','usvol':'U.S. VOLUNTEERS'}
def state(f):
    if f.startswith('Unreghst_uscol') : return 'U.S. COLORED TROOPS'
    if f.startswith('Unreghst_deafriq'): return 'LOUISIANA'
    if f.startswith('Unreghst_dt'): return 'DAKOTA TERRITORY'
    m=re.match(r'Unreghst_un(vetres|vetvol|usvol|rg|ind|[a-z]{2})',f)
    return ({'ind':'INDIAN TERRITORY'}.get(m.group(1)) or ST.get(m.group(1))) if m else None
C=json.load(open(H+'cwa_units.json'))
for c in C: c['state']=state(c['file'])
w=lambda s:re.findall(r"[a-z0-9]+",s.lower())
STOP={'regiment','independent','company','battery','the','of'}
key=lambda h:' '.join(x for x in w(h) if x not in STOP)
U=[json.loads(l) for l in open('data/dyers/units.jsonl')]
byst=collections.defaultdict(dict)
for c in C:
    if c['state']: byst[c['state']].setdefault(key(c['heading']),c)
N={r['unit_code']:r for r in map(json.loads,open('data/nps_us/units.jsonl'))}
L={l['unit_id']:l for l in csv.DictReader(open('data/scores/dyer_to_nps.csv'))}
match={}
for u in U:
    d=byst.get(u['state'],{}); k=key(u['heading'])
    if k in d: match[u['id']]=d[k]
    else:
        m=difflib.get_close_matches(k,list(d),n=1,cutoff=0.85)
        if m: match[u['id']]=d[m[0]]
used={id(c) for c in match.values()}
print('Dyer units',len(U),'matched to CWA',len(match),'| CWA entries',len(C),'unmatched CWA',sum(id(c) not in used for c in C))
json.dump({k:{'file':c['file'],'anchor':c['anchor'],'heading':c['heading']} for k,c in match.items()},open(H+'match.json','w'))
cat=collections.Counter(); extra=[]; vote=collections.Counter(); sims=[]; votes_ex=[]
for u in U:
    c=match.get(u['id']); l=L.get(u['id']); n=N.get(l['unit_code']) if l and l['status']=='linked' else None
    nps='nps text' if n and not n['empty'] else ('nps empty' if n else 'no nps')
    cwa='cwa' if c and len(c['text'].split())>5 else 'no cwa'
    cat[(cwa,nps)]+=1
    if cwa=='cwa' and nps=='nps text':
        a,b,o=w(c['text']),w(n['overview']),w(u['text'])
        sm=difflib.SequenceMatcher(None,b,a,autojunk=False); sims.append(sm.ratio())
        ins=[a[j1:j2] for t,i1,i2,j1,j2 in sm.get_opcodes() if t in('insert','replace') and j2-j1>=6]
        ins=[x for x in ins if 'copyright' not in x and 'source' not in x[:2]]
        if ins: extra.append((u['id'],sum(map(len,ins)),' '.join(max(ins,key=len))[:160]))
        so=difflib.SequenceMatcher(None,o,b,autojunk=False); cs=collections.Counter(a); oc=collections.Counter(o); nc=collections.Counter(b)
        for t,i1,i2,j1,j2 in so.get_opcodes():
            if t=='replace' and i2-i1==1==j2-j1:
                x,y=o[i1],b[j1]
                v='cwa=ocr' if cs[x]>=oc[x] and cs[y]<nc[y] else 'cwa=nps' if cs[y]>=nc[y] and cs[x]<oc[x] else 'unclear'
                vote[v]+=1
                if v=='cwa=ocr' and re.fullmatch(r'\d+',x) : votes_ex.append((u['id'].split('/')[1][:30],x,y))
for k,v in sorted(cat.items(),key=lambda x:-x[1]): print(v,k)
s=sorted(sims); print('CWA vs NPS word similarity deciles',[round(s[int(len(s)*i/10)],3) for i in range(10)])
print('units where CWA has >=6-word runs NPS lacks:',len(extra),' total words',sum(e[1] for e in extra))
for e in sorted(extra,key=lambda e:-e[1])[:15]: print(' ',e)
print('NPS-vs-OCR one-word disagreements; CWA agrees with:',vote)
print('numbers where CWA backs OCR over NPS (NPS typo):',len(votes_ex),votes_ex[:15])
