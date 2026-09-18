import os, sys, json, time
sys.path.insert(0,'tier0')
from wikipedia_volumes import run

def _build(name):
    """Default build-output path. Never /tmp: macOS cleaned it and destroyed a
    fully-built catalogue. Outputs belong beside the cache, inside the repo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(root, "build")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


SERIES = ["black clover","chainsaw man","dandadan","demon slayer","fire force","frieren",
          "gyo","horimiya","jujutsu kaisen","kaiju no 8","my dress up darling",
          "my hero academia","re zero","solo leveling","sword art online","witch hat atelier"]

rows=[]; out={}
for s in SERIES:
    try: r=run(s)
    except Exception as e: r={"series":s,"error":str(e)[:60]}
    out[s]=r
    v=r.get("volumes",[])
    n=len(v)
    M=lambda x,role: (x.get("markets") or {}).get(role) or {}
    jp_day=sum(1 for x in v if M(x,"original").get("date_precision")=="day")
    en_day=sum(1 for x in v if M(x,"licensed").get("date_precision")=="day")
    jp_isbn=sum(1 for x in v if M(x,"original").get("isbn13"))
    en_isbn=sum(1 for x in v if M(x,"licensed").get("isbn13"))
    ch=sum(1 for x in v if x.get("chapters"))
    rows.append((s, r.get("article","-"), n, jp_day, en_day, jp_isbn, en_isbn, ch, r.get("error","")))
    time.sleep(0.4)

json.dump(out, open(_build("tier0_16.json"),"w"), ensure_ascii=False)
print(f"{'series':<22}{'vols':>5}{'JPday':>7}{'ENday':>7}{'JPisbn':>8}{'ENisbn':>8}{'chap':>6}  article/error")
print("-"*104)
tot=[0]*6
for s,a,n,jd,ed,ji,ei,ch,err in rows:
    print(f"{s:<22}{n:>5}{jd:>7}{ed:>7}{ji:>8}{ei:>8}{ch:>6}  {err or a[:38]}")
    for i,x in enumerate((n,jd,ed,ji,ei,ch)): tot[i]+=x
print("-"*104)
print(f"{'TOTAL':<22}{tot[0]:>5}{tot[1]:>7}{tot[2]:>7}{tot[3]:>8}{tot[4]:>8}{tot[5]:>6}")
if tot[0]:
    print(f"\n  JP day-precision: {tot[1]/tot[0]*100:.1f}%   EN day-precision: {tot[2]/tot[0]*100:.1f}%")
    print(f"  JP ISBN: {tot[3]/tot[0]*100:.1f}%   EN ISBN: {tot[4]/tot[0]*100:.1f}%   chapter composition: {tot[5]/tot[0]*100:.1f}%")
