import json,subprocess,sys,os,urllib.request,hashlib,csv
S=sys.argv[1]; GW='https://ipfs.feralfile.com/ipfs/'; CDN='https://cdn.feralfileassets.com/previews/71e2bed5-e224-4ead-8fea-88a8cc067dbe/1706081014/'
ROOT='Qma2VZMhsrMjrbCZcJQXuF71XTwRdL45EPH97KC8BHo8Pd'
ipfs_dir=os.path.join(S,'art-ipfs'); cdn_dir=os.path.join(S,'art-cdn')
def get(url,binary=True):
    for i in range(3):
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'ff-filum-prep'}),timeout=120); return r.read(), r.status
        except urllib.error.HTTPError as e: return b'', e.code
        except Exception as e:
            if i==2: raise
def node(cid):
    raw,st=get(GW+cid+'?format=raw'); assert st==200,(cid,st)
    subprocess.run(['ipfs','--offline','block','put','--cid-codec=dag-pb','--mhtype=sha2-256'],input=raw,capture_output=True,check=True)
    return json.loads(subprocess.run(['ipfs','--offline','dag','get',cid],capture_output=True,check=True).stdout)
def is_dir(cid):
    # unixfs Data field: first bytes 0x08 0x01 = Type Directory; files are 0x08 0x02
    d=node(cid); b=d.get('Data',{}).get('/',{}).get('bytes','')
    import base64; raw=base64.b64decode(b+'='*(-len(b)%4))
    return raw[:2]==b'\x08\x01', d
rows=[]
def walk(cid,rel):
    isd,d=is_dir(cid)
    if not isd:
        rows.append((rel,cid)); return
    for l in d['Links']: walk(l['Hash']['/'], (rel+'/' if rel else '')+l['Name'])
walk(ROOT,'')
print('leaf files:',len(rows))
rep=[]
for rel,cid in rows:
    ib,ist=get(GW+cid); cb,cst=get(CDN+rel)
    for base,b in ((ipfs_dir,ib),(cdn_dir,cb)):
        p=os.path.join(base,rel); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'wb').write(b)
    same = ib==cb
    rep.append((rel,cid,ist,len(ib),cst,len(cb),'identical' if same else 'DIFF'))
    print(f'{rel:40s} ipfs={ist}/{len(ib):>7} cdn={cst}/{len(cb):>7} {"identical" if same else "DIFF"}')
w=csv.writer(open(os.path.join(S,'art_compare.csv'),'w')); w.writerow(['path','ipfs_cid','ipfs_http','ipfs_bytes','cdn_http','cdn_bytes','verdict']); w.writerows(rep)
# reproduce the dir CID locally from the IPFS bytes
out=subprocess.run(['ipfs','add','-n','-Q','-r','--cid-version','0',ipfs_dir],capture_output=True,text=True)
print('reproduced dir CID:',out.stdout.strip(),'| expected',ROOT,'| MATCH' if out.stdout.strip()==ROOT else '| MISMATCH')
