import csv,os,sys,urllib.request,time,subprocess,json
from concurrent.futures import ThreadPoolExecutor
S=sys.argv[1]; GW='https://ipfs.feralfile.com/ipfs/'
links=list(csv.DictReader(open(os.path.join(S,'QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1.links.csv'))))
dst=os.path.join(S,'truth-src'); os.makedirs(dst,exist_ok=True)
def one(r):
    p=os.path.join(dst,r['name'])
    if os.path.exists(p) and os.path.getsize(p)>0: return 'cached'
    for i in range(4):
        try:
            b=urllib.request.urlopen(urllib.request.Request(GW+r['cid'],headers={'User-Agent':'ff-filum-prep'}),timeout=90).read()
            open(p,'wb').write(b); return 'ok'
        except Exception as e:
            time.sleep(3*(i+1)); err=e
    return f'FAIL {err}'
with ThreadPoolExecutor(8) as ex: res=list(ex.map(one,links))
from collections import Counter; print(Counter(x.split()[0] for x in res))
fails=[(l['name'],x) for l,x in zip(links,res) if x.startswith('FAIL')]; print('fails:',fails[:5])
# verify each file's CID and reproduce the dir
bad=0
for l in links:
    c=subprocess.run(['ipfs','add','-n','-Q','--cid-version','0',os.path.join(dst,l['name'])],capture_output=True,text=True).stdout.strip()
    if c!=l['cid']: bad+=1; print('CID MISMATCH',l['name'],c,l['cid'])
print('per-file CID mismatches:',bad)
out=subprocess.run(['ipfs','add','-n','-Q','-r','--cid-version','0',dst],capture_output=True,text=True).stdout.strip()
print('reproduced base dir CID:',out,'| MATCH' if out=='QmQjzvrvZjzNGiqQhTGsiHeTpb9FmEcjCVWxVySf5FANC1' else '| MISMATCH')
# classify docs: series + animation_url dir
from collections import Counter
ser=Counter(); anim=Counter(); img=Counter()
for l in links:
    d=json.load(open(os.path.join(dst,l['name'])))
    s=next((a['value'] for a in d.get('attributes',[]) if a.get('trait_type')=='Series'),'?')
    ser[s]+=1
    if s=='filum':
        anim[d.get('animation_url','').split('?')[0]]+=1; img[d.get('image','').split('?')[0]]+=1
print('series:',dict(ser)); print('filum animation_url bases:',dict(anim)); print('filum image bases:',dict(img))
