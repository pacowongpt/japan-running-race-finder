#!/usr/bin/env python3
"""Conservative updater: check opt-in official pages; update only structured Event JSON-LD.
Never infer a race date/grade from unrelated page text. Preserve previous verified data.
"""
import datetime as dt, json, pathlib, re, urllib.request, urllib.robotparser, urllib.parse, time
from html.parser import HTMLParser
BASE=pathlib.Path(__file__).resolve().parent
class Scripts(HTMLParser):
    def __init__(self): super().__init__();self.on=False;self.buff='';self.scripts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and 'ld+json' in dict(attrs).get('type','').lower():self.on=True;self.buff=''
    def handle_data(self,data):
        if self.on:self.buff+=data
    def handle_endtag(self,tag):
        if tag=='script' and self.on:self.scripts.append(self.buff);self.on=False

def crawl(url):
    host=urllib.parse.urlsplit(url)
    if host.scheme!='https' or not host.hostname:return None
    agent='JapanRaceFinder-Personal/0.1 (+source-check; respectful-fetch)'
    robots=urllib.robotparser.RobotFileParser();robots.set_url(f'{host.scheme}://{host.netloc}/robots.txt')
    try:robots.read()
    except Exception as e:print('robots unreachable, skip',url,str(e));return None
    if not robots.can_fetch(agent,url):print('robots disallow',url);return None
    req=urllib.request.Request(url,headers={'User-Agent':agent,'Accept':'text/html'})
    with urllib.request.urlopen(req,timeout=15) as r:
        if 'text/html' not in r.headers.get('Content-Type',''):return None
        raw=r.read(1024*1024+1)
        if len(raw)>1024*1024:return None
        return raw.decode('utf-8','replace')

def iter_events(obj):
    if isinstance(obj,list):
        for i in obj:yield from iter_events(i)
    if isinstance(obj,dict):
        typ=obj.get('@type',[]);typ=[typ] if isinstance(typ,str) else typ
        if any(str(t).lower()=='event' for t in typ):yield obj
        if '@graph' in obj:yield from iter_events(obj['@graph'])

def parse_event(html):
    p=Scripts();p.feed(html)
    for script in p.scripts:
        try:doc=json.loads(script)
        except Exception:continue
        for e in iter_events(doc):
            d=str(e.get('startDate',''))[:10]
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',d):yield {'date':d,'name':str(e.get('name',''))}

def run():
    target=BASE/'data/races.json';feed=json.loads(target.read_text());sources=json.loads((BASE/'sources.json').read_text())['sources']
    byid={r['id']:r for r in feed['races']};checked=0;changed=0
    for src in sources:
        if not src.get('enabled') or src.get('id') not in byid:continue
        try:
            html=crawl(src['url']);checked+=1
            if not html:continue
            events=list(parse_event(html))
            # Require one official structured Event with exact normalized race name.
            normalize=lambda x:re.sub(r'[^\w]+','',x,flags=re.UNICODE).casefold()
            race=byid[src['id']]
            matches=[e for e in events if normalize(e['name'])==normalize(race['name'])]
            dates={e['date'] for e in matches}
            if len(dates)==1:
                newdate=next(iter(dates));old=race['date']
                if newdate!=old:
                    if abs((dt.date.fromisoformat(newdate)-dt.date.fromisoformat(old)).days)>60:
                        print('Large date change needs human review:',src['id'],old,'->',newdate)
                    else:
                        race['date']=newdate
                        race['statusNote']='官方結構化資料日期變更（自動更新）；報名條件請再核實'
                        race['autoCheckedAt']=dt.date.today().isoformat()
                        changed+=1
                        print('Updated official structured date:',src['id'],old,'->',newdate)
            elif len(dates)>1:print('Ambiguous event dates; skipped',src['id'])
        except Exception as e:print('skip',src['id'],type(e).__name__,str(e)[:150])
        time.sleep(2)
    # Only update generatedAt on actual changed approved data; otherwise preserve freshness indicator.
    if changed:
        feed['generatedAt']=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')
        target.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n')
    print(f'Checked {checked} pages; automatic date changes {changed}. Other data preserved.')
if __name__=='__main__':run()
