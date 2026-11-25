import re, math, csv, sys, json, os
from datetime import date

# ---------------- category pages ----------------
CATS = {
 # name: unit-period, gst, target, walk, R, beta, limit, pack
 'training':        dict(gst=.18,T=6000,W=7500,R=3,B=1,A=900000),
 'catering':        dict(gst=.05,T=280,W=340,R=3,B=1,A=600000),
 'cleaning':        dict(gst=.18,T=85000,W=100000,R=4,B=2,A=900000,per='month'),
 'cloud-servers':   dict(gst=.18,T=96000,W=115000,R=5,B=3,A=6000000,per='year'),
 'courier':         dict(gst=.18,T=160,W=200,R=4,B=2,A=500000),
 'crm-licenses':    dict(gst=.18,T=18000,W=22000,R=4,B=2,A=2500000,per='year'),
 'design-software': dict(gst=.18,T=30000,W=36000,R=4,B=2,A=1500000,per='year'),
 'headsets':        dict(gst=.18,T=3500,W=4200,R=3,B=1,A=400000),
 'laptops':         dict(gst=.18,T=62000,W=70000,R=4,B=2,A=4000000),
 'led-lighting':    dict(gst=.18,T=1800,W=2200,R=3,B=1,A=350000),
 'mobile-phones':   dict(gst=.18,T=24000,W=28000,R=4,B=2,A=2000000),
 'monitors':        dict(gst=.18,T=14000,W=16500,R=3,B=1,A=1200000),
 'office-chairs':   dict(gst=.18,T=9000,W=11000,R=3,B=1,A=700000),
 'printer-paper':   dict(gst=.12,T=2200,W=2600,R=3,B=1,A=250000),
 'security-guards': dict(gst=.18,T=21000,W=25000,R=4,B=2,A=1000000,per='month'),
}
# (effective date, category, field, value)
AMENDS = [
 ('2026-09-22','courier','W',210), ('2026-11-11','cloud-servers','W',119990),
 ('2026-11-25','mobile-phones','W',29780), ('2026-09-20','catering','T',270),
 ('2026-11-06','printer-paper','W',2780), ('2026-11-09','headsets','A',320000),
 ('2026-12-05','led-lighting','W',2360), ('2026-12-04','led-lighting','W',2330),
 ('2026-12-14','monitors','A',960000),
]
RATES = {'USD':84.5,'EUR':91,'GBP':106}
# ---------------- suppliers (FILL FROM suppliers/ folder) ----------------
# status: ACTIVE / PROBATION / BLACKLISTED ; caps {category: walkaway}; rates {cur: inr}
SUPPLIERS = {}
def load_suppliers():
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),'suppliers.json')
    if os.path.exists(p):
        SUPPLIERS.update(json.load(open(p)))
load_suppliers()

# ---------------- money parsing ----------------
CUR = r'(?:₹|Rs\.?|INR|US\$|USD|\$|EUR|€|GBP|£|AED|JPY|SGD|¥)'
AMT = r'\d[\d,]*(?:\.\d+)?(?:\s?(?:lakhs?|crore|k)\b)?'
MONEY = re.compile(r'(?P<cur>'+CUR+r')\s?(?P<amt>'+AMT+')', re.I)
CURMAP = {'₹':'INR','rs':'INR','rs.':'INR','inr':'INR','$':'USD','us$':'USD','usd':'USD','€':'EUR','eur':'EUR','£':'GBP','gbp':'GBP','aed':'AED','sgd':'SGD','jpy':'JPY','¥':'JPY'}
def num(s):
    s=s.lower().strip(); mult=1
    m=re.search(r'(lakhs?|crore|k)$',s)
    if m:
        mult={'k':1e3,'crore':1e7}.get(m.group(1),1e5); s=s[:m.start()].strip()
    return float(s.replace(',',''))*mult
W1={w:i for i,w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
W2={'twenty':20,'thirty':30,'forty':40,'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90}
def words_to_num(txt):
    cur=0; tot=0
    for w in re.split(r'[\s\-]+',txt.lower().strip()):
        if w in W1: cur+=W1[w]
        elif w in W2: cur+=W2[w]
        elif w=='hundred': cur*=100
        elif w=='thousand': tot+=cur*1000; cur=0
        elif w in('lakh','lakhs'): tot+=cur*100000; cur=0
        elif w=='and': pass
        else: return None
    return tot+cur
WORDMONEY = re.compile(r'((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakhs?|and)[\s\-]+)+)rupees', re.I)

def find_money(line):
    out=[]
    for m in MONEY.finditer(line):
        cur=CURMAP[m.group('cur').lower()]
        out.append((m.start(),cur,num(m.group('amt'))))
    for m in WORDMONEY.finditer(line):
        v=words_to_num(m.group(1))
        if v is not None: out.append((m.start(),'INR',float(v)))
    out.sort()
    return out

# ---------------- thread splitting ----------------
def split_thread(msg):
    parts=re.split(r'\n?\[(Earlier|Latest) message — ([^\]]*)\]\n',  '\n'+msg)
    if len(parts)==1: return [], msg
    earlier=[]; latest=msg
    # parts: [pre, kind, hdr, body, kind, hdr, body...]
    for i in range(1,len(parts),3):
        kind,hdr,body=parts[i],parts[i+1],parts[i+2]
        if kind=='Earlier': earlier.append((hdr,body.strip()))
        else: latest=body.strip()
    return earlier, latest

# ---------------- offer parsing ----------------
GST_INC = re.compile(r'(incl(?:uding|usive|\.)?\s*(?:of\s*)?GST|GST\s*(?:is\s*)?(?:included|incl))', re.I)
def parse_offer(text, qty, cat, supplier, prev=None):
    """returns normalized INR excl GST per category unit, or None (missing info)"""
    info=CATS[cat]
    lines=[l for l in text.split('\n') if find_money(l) or re.search(r'further\s+[\d.]+%\s+off our previous',l,re.I)]
    if not lines: return None
    line=lines[0]
    per=info.get('per')
    mon=find_money(line)
    rates=dict(RATES); rates.update(SUPPLIERS.get(supplier,{}).get('rates',{}))
    def inr(cur,amt):
        if cur=='INR': return amt
        if cur in rates: return amt*rates[cur]
        return None
    low=line.lower()
    # (a) further discount on previous quote
    m=re.search(r'further\s+([\d.]+)%\s+off our previous',line,re.I)
    if m and not mon:
        if prev is None: return None
        return prev*(1-float(m.group(1))/100)
    vals=[]
    for _,cur,amt in mon:
        v=inr(cur,amt)
        if v is None: return None
        vals.append(v)
    # (b) total
    m=re.search(r'in total for all\s+(\d+)',line,re.I)
    if m: p=vals[0]/int(m.group(1))
    elif re.search(r'discount on our list price',line,re.I):
        d=float(re.search(r'([\d.]+)%\s*discount',line,re.I).group(1))
        p=vals[0]*(1-d/100)
    elif re.search(r'\bbetween\b',low) and len(vals)>=2:
        p=max(vals[:2])
    elif re.search(r'orders? of up to\s+(\d+)',low) and len(vals)>=2:
        n=int(re.search(r'orders? of up to\s+(\d+)',low).group(1))
        p=vals[0] if qty<=n else vals[1]
    else:
        p=vals[0]
        m=re.search(r'further\s+([\d.]+)%\s+off for orders of\s+(\d+)',low)
        if m and qty>=int(m.group(2)): p*=1-float(m.group(1))/100
        m=re.search(r'plus\s+(\d+)\s+free\s+\w+\s+for every\s+(\d+)',low)
        if m:
            k,mm=int(m.group(1)),int(m.group(2)); p=p*mm/(mm+k)
    # unit conversion
    if re.search(r'per dozen',low): p/=12
    else:
        m=re.search(r'per pack of\s+(\d+)',low) or re.search(r'per\s+(\d+)\s+[a-z]+',low)
        if m: p/=int(m.group(1))
    if cat=='printer-paper' and re.search(r'per ream',low): p*=10
    # period
    if per:
        isy=re.search(r'per year|yearly|annual|a year|/year|per annum',low)
        ism=re.search(r'per month|monthly|a month|/month',low)
        if isy and not ism: stated='year'
        elif ism and not isy: stated='month'
        else: return None
        if per=='month' and stated=='year': p/=12
        if per=='year' and stated=='month': p*=12
    if GST_INC.search(line): p/=1+info['gst']
    return p

# ---------------- detectors ----------------
INJ = [r'language model',r'\bAI agent\b',r'\bbot\b',r'automated system',r'reviewing assistant',r'<!--.*?assistant',
       r'admin override',r'override',r'ignore (?:your|all|any|previous|prior)',r'pre-?approved',r'approval (?:was |is )?already granted',
       r'signed off',r'सहायक',r'SYSTEM NOTE',r'system prompt',r'\bAI (?:assistant|system|model|reviewer)\b',r'as an AI',
       r'\bLLM\b',r'\bchatbot\b',r'to the (?:AI|model|assistant)',r'for the (?:AI|model|assistant)',r'reviewer']
INJ_RE=[re.compile(p,re.I|re.S) for p in INJ]
def is_injection(full):
    return any(r.search(full) for r in INJ_RE)

def banned(latest):
    t=re.sub(r'no automatic renewal[^.]*\.?','',latest,flags=re.I)
    t=re.sub(r'(not (asking|seeking|requiring|requesting)( for| any)?|no|without|non-?|does not (require|need|ask for))[\s-]*exclusiv\w*( (is|are) (asked|required|needed|requested))?( asked| required| needed| requested)?','',t,flags=re.I)
    if re.search(r'auto-?renew|automatic(?:ally)? renew|renews? (?:automatically|on its own)|renews on its own|year to year unless|continues? (?:from )?year to year|evergreen',t,re.I): return True
    if re.search(r'unlimited',t,re.I) and re.search(r'liabilit',t,re.I): return True
    if re.search(r'exclusive supplier|exclusively from|only from us|sole supplier|exclusiv',t,re.I): return True
    # advance/upfront
    for m in re.finditer(r'([\d.]+)\s*%[^.\n]*?(?:upfront|up-front|advance|in advance)',t,re.I):
        if float(m.group(1))>30: return True
    for m in re.finditer(r'(?:upfront|up-front|advance)[^.\n]*?([\d.]+)\s*%',t,re.I):
        if float(m.group(1))>30: return True
    if re.search(r'\bhalf\b[^.\n]*(?:upfront|advance)|(?:upfront|advance)[^.\n]*\bhalf\b',t,re.I): return True
    for w,v in {'forty':40,'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90,'hundred':100,'thirty-five':35,'full':100}.items():
        if re.search(r'\b%s\s*(?:per ?cent|%%)?[^.\n]*(?:upfront|advance)'%w,t,re.I): return True
    return False

# ---------------- decision ----------------
def params(cat, d, supplier):
    info=dict(CATS[cat])
    for eff,c,f,v in sorted(AMENDS):
        if c==cat and eff<=d: info[f]=v
    cap=SUPPLIERS.get(supplier,{}).get('caps',{}).get(cat)
    if cap is not None: info['W']=cap
    return info

def analyze(row):
    """full decision with a step-by-step trace (used by the Streamlit app)"""
    cat=row['category']; qty=int(row['quantity']); sup=row['supplier']
    r=int(row['round']); msg=row['supplier_message']
    earlier,latest=split_thread(msg)
    tr=[('pass','')]*6
    def done(a,re_,pr,step,note,**x):
        t=list(tr); t[step]=('fire',note)
        for k in range(step+1,6): t[k]=('skip','not reached')
        return dict(action=a,reason=re_,price=pr,label='%s:%s:%s'%(a,re_,'' if pr is None else pr),trace=t,**x)
    prev=None
    for hdr,body in reversed(earlier):
        if hdr.startswith(sup):
            prev=parse_offer(body,qty,cat,sup); break
    p=parse_offer(latest,qty,cat,sup,prev)
    if p is None: return done('ESCALATE','MISSING_INFO',None,0,'No usable price (no number, no billing period, or currency not in the table)')
    tr[0]=('pass','Normalized offer p = Rs %.2f'%p)
    status=SUPPLIERS.get(sup,{}).get('status','ACTIVE')
    if status=='BLACKLISTED': return done('REJECT','BLACKLISTED_SUPPLIER',None,1,sup+' is blacklisted',p=p)
    tr[1]=('pass','Status: '+status)
    if is_injection(msg): return done('ESCALATE','PROMPT_INJECTION',None,2,'Text aimed at an AI / claims pre-approval found in the thread',p=p)
    tr[2]=('pass','No instructions aimed at an AI')
    if banned(latest): return done('ESCALATE','BANNED_TERM',None,3,'Banned contract term in the latest message',p=p)
    tr[3]=('pass','No banned terms in the latest message')
    info=params(cat,row['date'],sup)
    R=info['R']; rr=min(r,R); T,W=info['T'],info['W']
    L=T if status=='PROBATION' else T+(W-T)*(((rr-1)/(R-1))**info['B'])
    x=dict(p=p,L=L,T=T,W=W,A=info['A'],total=p*qty)
    ls='L(r=%d) = Rs %.2f%s'%(r,L,' (probation: target)' if status=='PROBATION' else '')
    if p<=L+1e-9:
        tr[4]=('pass','p <= '+ls)
        if p*qty>info['A']: return done('ESCALATE','OVER_APPROVAL_LIMIT',None,5,'Order Rs %s exceeds limit Rs %s'%(format(round(p*qty),','),format(info['A'],',')),**x)
        tr[5]=('pass','Order Rs %s is within limit Rs %s'%(format(round(p*qty),','),format(info['A'],',')))
        return done('ACCEPT','ACCEPTABLE_PRICE',None,5,tr[5][1],**x)|{'trace':tr}
    if r>=R: return done('REJECT','ABOVE_WALKAWAY',None,4,'p > '+ls+' on the final round',**x)
    return done('COUNTER','COUNTER_OFFER',math.floor(L+0.5),4,'p > '+ls+' so counter at the ladder value',**x)

def decide(row):
    return analyze(row)['label']

if __name__=='__main__':
    inp,out=sys.argv[1],sys.argv[2]
    with open(inp,newline='',encoding='utf-8') as f: rows=list(csv.DictReader(f))
    with open(out,'w',newline='') as f:
        w=csv.writer(f,lineterminator='\n'); w.writerow(['thread_id','label'])
        for r in rows: w.writerow([r['thread_id'],decide(r)])
