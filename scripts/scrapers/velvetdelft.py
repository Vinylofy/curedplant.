"""Velvet Delft: robots-aware, listing-first LPos collector. No database access."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from scripts.importers.common import strict_normalize_gtin

BASE = 'https://www.velvetdelft.nl'
SHOP_ID = 'velvetdelft'
DETAIL_REVISION = 'velvetdelft-detail-v1'
USER_AGENT = 'VinylofyVelvetDelftResearch/1.0'
GENRES = ('countryblues','danceelektronisch','heavy-metal','hip-hop','jazz','kpop','nederlands','poprock','prog','reggae','soulrnb','soundtracks','wereld')
# Verified against the current Jazz / Sale controls (see source proof).
VINYL_MEDIA = {'5':'10-inch','6':'LP','7':'12-inch maxi-single','11':'7-inch single'}
COLLECTIONS = ('nieuw-binnen','vinyl-sale','speciale-uitgaven','Gekleurd-vinyl-actie','black-friday-special-releases','national-album-day-2026')
RELEASE = re.compile(r'^/(?:nl|en)/release/(\d+)/', re.I)
VINYL = re.compile(r'^(?:\d+\s*-?\s*)?(LP|7\s*-?\s*inch(?:\s+single)?|10\s*-?\s*inch(?:\s+single)?|12\s*-?\s*inch(?:\s+maxi(?:-single)?)?)$',re.I)
USED = re.compile(r'\b(tweedehands|2e\s*hands|second[ -]?hand|pre[ -]?owned|used\s+vinyl)\b',re.I)
PAGER = re.compile(r'Pagina\s+(\d+)\s+van totaal\s+([\d.]+)\.\s*Totaal resultaten:\s*([\d.]+)\.\s*\(getoond:\s*(\d+)\s+items\)',re.I)
FIELDS = ('source_product_id','source_url','artist','title','format','price','regular_price','currency','availability','availability_raw','listing_observed_at','listing_url','condition','ean','gtin14','ean_status','detail_observed_at','detail_next_at','reason')


def now(): return datetime.now(timezone.utc).isoformat()
def text(node): return node.get_text(' ',strip=True) if node else ''
def safe_url(url, product=False):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in ('velvetdelft.nl','www.velvetdelft.nl') or p.username or p.password or p.port not in (None,443) or p.fragment:
        raise ValueError('Unsafe source URL')
    if product and not RELEASE.match(p.path): raise ValueError('Invalid release URL')
    return url


def save(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)


def robots_allows(parser,lines,url):
    # stdlib RobotFileParser does not interpret Google's '*' path extension.
    if not parser.can_fetch(USER_AGENT,url):return False
    applies=False
    for raw in lines:
        entry=raw.split('#',1)[0].strip()
        if ':' not in entry:continue
        key,value=[x.strip() for x in entry.split(':',1)]
        if key.lower()=='user-agent':applies=value=='*' or value.lower() in USER_AGENT.lower()
        elif applies and key.lower()=='disallow' and value and '*' in value:
            pattern=re.escape(value).replace(r'\*','.*')
            if pattern.endswith(r'\$'):pattern=pattern[:-2]+'$'
            if re.match(pattern,urlsplit(url).path+'?'+urlsplit(url).query):return False
    return True


class Transport:
    """Single flight, no challenge handling; retries only bounded 5xx failures."""
    def __init__(self, delay=3.0):
        if delay<3:raise ValueError('Minimum request interval is three seconds')
        self.delay=delay;self.last=0.;self.requests=[];self.robots=RobotFileParser()
        self.session=requests.Session();self.session.headers['User-Agent']=USER_AGENT
        raw=self._request(BASE+'/robots.txt',robots=True)
        self.robots.parse(raw.splitlines())
        self.robot_rules=raw.splitlines()
        self.delay=max(delay,self.robots.crawl_delay(USER_AGENT) or 0)
    def _request(self,url,robots=False,data=None,headers=None):
        safe_url(url)
        if not robots and not robots_allows(self.robots,getattr(self,'robot_rules',[]),url):raise RuntimeError('robots.txt disallows '+url)
        for attempt in range(2):
            time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            r=(self.session.post(url,data=data,headers=headers,timeout=(10,30),allow_redirects=False) if data is not None else self.session.get(url,timeout=(10,30),allow_redirects=False))
            self.requests.append({'url':url,'status':r.status_code,'bytes':len(r.content),'observed_at':now(),'method':'POST' if data is not None else 'GET','listing_parameters':data})
            if r.status_code in (502,503,504) and attempt==0 and not robots:
                time.sleep(max(10,self.delay));continue
            if r.status_code!=200:raise RuntimeError(f'HTTP {r.status_code}; stopped: {url}')
            if len(r.content)>8_000_000:raise RuntimeError('Unexpected response size')
            if re.search(r'<title[^>]*>[^<]*(?:captcha|access denied|just a moment)',r.text,re.I):raise RuntimeError('Access challenge; stopped')
            return r.text
        raise RuntimeError('Unreachable retry state')
    def get(self,url):return self._request(url)
    def post_listing(self,payload,csrf):return self._request(BASE+'/products/blockitems',data=payload,headers={'X-CSRF-Token':csrf,'X-Requested-With':'XMLHttpRequest'})


def availability(value):
    v=value.lower().strip()
    if re.search(r'pre[ -]?order|voorbestell',v):return 'preorder'
    if re.search(r'niet beschikbaar|uitverkocht|sold out|out of stock',v):return 'out_of_stock'
    if re.search(r'leverancier|bestelbaar|op bestelling|verwacht:\s*\d+\s*dagen',v):return 'supplier_order'
    if re.fullmatch(r'op voorraad(?:\s+.*)?',v):return 'in_stock'
    return 'unknown'


def price(card):
    node=card.select_one('[onclick^="add_to_cart"], [onclick^="add_to_cart_limited"]')
    if node is None:
        # Unavailable cards intentionally have no cart handler.
        nodes=[n for n in card.select('.btn-lpos') if '€' in text(n) and not n.select_one('.btn-lpos')]
        if len(nodes)!=1:return None,None
        node=nodes[0]
    copy=BeautifulSoup(str(node),'html.parser')
    regular=[]
    for old in copy.select('del,s,strike,.old-price,[style*="line-through"]'):
        regular+=re.findall(r'€\s*([\d.]+,\d{2})',text(old));old.decompose()
    amounts=re.findall(r'€\s*([\d.]+,\d{2})',text(copy))
    if len(amounts)!=1:return None,None
    val=Decimal(amounts[0].replace('.','').replace(',','.'))
    if val<=0:return None,None
    return str(val),regular[0].replace('.','').replace(',','.') if regular else None


def url_codes(url):
    tail=urlsplit(url).path.rstrip('/').split('/')[-1]
    return [tail] if tail.isascii() and tail.isdigit() and len(tail) in (8,12,13,14) else []


def block_config(html):
    s=BeautifulSoup(html,'html.parser')
    containers=[n for n in s.select('[id^="items"]') if n.select('.productcard')]
    if not containers:return None
    block=containers[0]['id'].removeprefix('items')
    if not block.isdigit():raise ValueError('Invalid public catalogue block')
    def val(key):
        n=s.find(id=key+block);return n.get('value','') if n else ''
    keys=('g','t','m','s','d','v','l','p','fsmin','fsmax','pricemin','pricemax','releasemin','releasemax','onlistonly','pgonly','eas','ets','ssb','view','sort','direction','showreleases','wholesalers')
    payload={k:val(k) for k in keys if val(k)}
    for key in ('genres','tags'):
        nodes=s.select(f'input[name="{key}{block}"]')
        checked=[n for n in nodes if n.has_attr('checked')]
        value=','.join(n.get('value','') for n in (checked or nodes) if n.get('value'))
        if value:payload[key]=value
    # IDs are read from the site's own format controls, never guessed.
    formats={}
    for n in s.select(f'input[name="media{block}"][type="checkbox"]'):
        label=s.find('label',attrs={'for':n.get('id')})
        if label and VINYL.fullmatch(text(label)):formats[n['value']]=text(label)
    if any(VINYL_MEDIA.get(k)!=v for k,v in formats.items()):raise ValueError('Public media mapping changed')
    payload['media']=','.join(VINYL_MEDIA);payload['blockid']=block
    # Both are choices actually exposed by the UI's stock checkbox / page-size radios.
    payload['instockonly']='false'
    # The public paginator flag is needed on blocks whose UI hides pagination.
    payload['p']='true'
    limits=[n.get('value','') for n in s.select(f'input.limit{block}') if n.get('value','').isdigit()]
    allowed=[int(x) for x in limits if 1<=int(x)<=192]
    if not allowed:raise ValueError('Missing bounded public page size controls')
    payload['limit']=str(max(allowed))
    for key in ('sort','view'):
        selected=s.select_one(f'input.{"sortaa" if key=="sort" else key}{block}[checked]')
        if selected:payload[key]=selected.get('value','')
    token=s.select_one('meta[name="csrfToken"],input[name="_csrfToken"]')
    csrf=token.get('content') or token.get('value') if token else ''
    if not csrf:raise ValueError('Missing public session CSRF token')
    return {'payload':payload,'csrf':csrf,'formats':formats}


def parse_listing(html,url,observed=None):
    safe_url(url);s=BeautifulSoup(html,'html.parser');main=next((n for n in s.select('[id^="items"]') if n.select('.productcard')),None);cards=(main or s).select('.productcard');rows=[];excluded=[]
    if not cards:
        zero=PAGER.search(s.get_text(' ',strip=True))
        if not zero or int(zero.group(3).replace('.',''))!=0:raise ValueError('Listing structure changed or empty collection: '+url)
    for card in cards:
        a=card.select_one('a[hreflang][href*="/release/"]') or card.select_one('a[href*="/release/"]')
        if not a:raise ValueError('Card without release identity')
        source=safe_url(urljoin(BASE,a['href']),True);rid=RELEASE.match(urlsplit(source).path)[1]
        f=text(card.select_one('.carrier'));artist=text(card.select_one('.artist'))
        title_nodes=a.select('span');title=text(title_nodes[-1]) if len(title_nodes)>1 else text(a)
        raw_av=text(card.select_one('.deliverybtn'));p,old=price(card)
        condition='used' if USED.search(text(card)) else 'new'
        reason='non_vinyl_or_ambiguous_bundle' if not VINYL.fullmatch(f) else 'second_hand' if condition=='used' else None
        codes=[c for x in card.select('a[href*="/release/"]') for c in url_codes(urljoin(BASE,x['href']))]
        valid={strict_normalize_gtin(c) for c in codes if strict_normalize_gtin(c)}
        if len(valid)>1:reason='conflicting_listing_barcodes'
        row=dict(source_product_id=rid,source_url=source,artist=artist,title=title,format=f,price=p,regular_price=old,currency='EUR',availability=availability(raw_av),availability_raw=raw_av,listing_observed_at=observed or now(),listing_url=url,condition=condition,ean='',gtin14='',ean_status='pending',detail_observed_at='',detail_next_at='',reason=reason or '',url_barcodes=sorted(set(codes)))
        if not artist or not title:raise ValueError('Artist/title selector changed')
        (excluded if reason else rows).append(row)
    m=PAGER.search(s.get_text(' ',strip=True));next_url=None
    pagination={'page':1,'pages':None,'total':None,'shown':len(cards),'bounded_collection':not bool(m)}
    if m:
        current,pages,total,shown=[int(x.replace('.','')) for x in m.groups()]
        if shown!=len(cards) or current<1 or pages<current:raise ValueError('Pagination count mismatch')
        if total<shown:
            pagination['count_warning']='Publisher reports fewer total results than visible cards'
            pagination['bounded_collection']=True
        if current!=int(parse_qs(urlsplit(url).query).get('page',['1'])[0]):raise ValueError('Requested page ignored')
        pagination.update(page=current,pages=pages,total=total,shown=shown)
        if current<pages:
            for link in s.select('.pagination a[href]'):
                candidate=urljoin(BASE,link['href']);parsed=urlsplit(candidate)
                if parsed.path in (urlsplit(url).path, urlsplit(url).path.replace('/pagina/','/genre/'), '/products/blockitems') and parse_qs(parsed.query).get('page')==[str(current+1)]:
                    next_url=safe_url(candidate);break
            if not next_url:raise ValueError('Missing next page before catalogue end')
    elif s.select('.pagination a[href]'):raise ValueError('Unrecognized pagination')
    return {'records':rows,'excluded':excluded,'pagination':pagination,'next_url':next_url,'listing_sha256':hashlib.sha256(html.encode()).hexdigest()}


def enrich(row,html):
    """Never reads detail price/availability. Barcodes must agree across evidence."""
    result=dict(row);s=BeautifulSoup(html,'html.parser');canonical=s.select_one('link[rel="canonical"]')
    if not canonical:raise ValueError('Missing canonical release identity')
    url=safe_url(urljoin(BASE,canonical['href']),True)
    if RELEASE.match(urlsplit(url).path)[1]!=row['source_product_id']:raise ValueError('Detail release conflict')
    if not s.select_one('h1'):raise ValueError('Detail structure changed')
    if USED.search(text(s.select_one('h1'))+' '+text(s.select_one('h2'))):raise ValueError('Second hand detail')
    # Only the product specification labelled barcode, never track text/SKU.
    labels=[n for n in s.select('small') if text(n).lower() in ('barcode','ean','gtin','upc')]
    explicit=[text(n.parent.select_one('strong')) for n in labels]
    structured=[]
    for script in s.select('script[type="application/ld+json"]'):
        try:metadata=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        nodes=metadata if isinstance(metadata,list) else metadata.get('@graph',[metadata]) if isinstance(metadata,dict) else []
        for node in nodes:
            if not isinstance(node,dict) or node.get('@type')!='Product':continue
            if node.get('sku') and str(node['sku'])!=row['source_product_id']:continue
            structured.extend(str(node[k]) for k in ('gtin','gtin8','gtin12','gtin13','gtin14') if node.get(k))
    evidence=explicit+structured+row.get('url_barcodes',[])+url_codes(url)
    invalid=[c for c in evidence if c and (not strict_normalize_gtin(c) or not int(strict_normalize_gtin(c)))]
    valid={strict_normalize_gtin(c) for c in evidence if strict_normalize_gtin(c)}
    if invalid:raise ValueError('Invalid barcode checksum')
    if len(valid)>1:raise ValueError('Conflicting detail/listing barcode')
    gtin=next(iter(valid)) if valid else ''
    # Explicitly labelled detail barcode is required for first publication.
    confirmed=bool(gtin and explicit and any(strict_normalize_gtin(c)==gtin for c in explicit))
    result.update(ean=(gtin[1:] if gtin.startswith('0') else gtin) if confirmed else '',gtin14=gtin if confirmed else '',ean_status='verified' if confirmed else 'missing',detail_observed_at=now(),detail_next_at=(datetime.now(timezone.utc)+timedelta(days=90 if confirmed else 7)).isoformat(),detail_sha256=hashlib.sha256(html.encode()).hexdigest(),detail_parser_revision=DETAIL_REVISION)
    return result


def initial_routes(home):
    soup=BeautifulSoup(home,'html.parser');known={urlsplit(urljoin(BASE,a['href'])).path for a in soup.select('a[href]')}
    mandatory=GENRES+COLLECTIONS
    missing=[slug for slug in mandatory if '/nl/pagina/'+slug not in known]
    if missing:raise ValueError('Navigation routes missing: '+','.join(missing))
    return {slug:BASE+'/nl/pagina/'+slug for slug in mandatory}


def collect(mode='discovery',state_path='output/velvetdelft/state.json',max_pages=25,detail_limit=100,transport=None,refresh=False):
    path=Path(state_path);state=json.loads(path.read_text()) if path.exists() else {'version':1,'shop_id':SHOP_ID,'records':{},'categories':{},'requests':[]}
    if state.get('shop_id')!=SHOP_ID or state.get('version')!=1:raise ValueError('Wrong checkpoint')
    client=transport;state['error']=None;processed=0
    try:
        if client is None:client=Transport()
        if mode in ('discovery','prices'):
            if refresh and mode!='prices':state['categories']={}
            if mode=='prices' and (state.get('cycle_mode')!='prices' or not any(c.get('next') for c in state['categories'].values())):state['categories']={}
            state['cycle_mode']=mode
            home_html=client.get(BASE+'/nl');routes=initial_routes(home_html);routes={'home':BASE+'/nl',**routes}
            for category,url in routes.items():
                progress=state['categories'].setdefault(category,{'next':url,'pages':[],'seen_ids':[],'complete':False})
                if category=='home' and not progress['next']:progress['complete']=True
                if progress['pages'] and category!='home' and progress['pages'][-1].get('parameters',{}).get('p')!='true':
                    progress={'next':url,'pages':[],'seen_ids':[],'complete':False};state['categories'][category]=progress
                if not progress['next']:continue
                bootstrap=home_html if category=='home' else client.get(url)
                cfg=block_config(bootstrap) if category!='home' else None
                while progress['next'] and processed<max_pages:
                    page=int(parse_qs(urlsplit(progress['next']).query).get('page',['1'])[0])
                    current=url+('?page='+str(page) if page>1 else '')
                    html=client.post_listing({**cfg['payload'],'page':page},cfg['csrf']) if cfg else bootstrap
                    parsed=parse_listing(html,current);ids=[r['source_product_id'] for r in parsed['records']+parsed['excluded']]
                    if set(ids)&set(progress['seen_ids']):raise ValueError('Duplicate/repeated releases within category pagination')
                    for row in parsed['records']:
                        rid=row['source_product_id'];prior=state['records'].get(rid,{})
                        oldids={strict_normalize_gtin(c) for c in prior.get('url_barcodes',[]) if strict_normalize_gtin(c)}
                        newids={strict_normalize_gtin(c) for c in row.get('url_barcodes',[]) if strict_normalize_gtin(c)}
                        if oldids and newids and oldids!=newids:raise ValueError('Release barcode changed between categories')
                        if prior.get('ean_status')=='verified' and oldids==newids:
                            for key in ('ean','gtin14','ean_status','detail_observed_at','detail_next_at','detail_sha256','detail_parser_revision'):row[key]=prior.get(key,'')
                        row['categories']=sorted(set(prior.get('categories',[])+[category]));state['records'][rid]=row
                    progress['pages'].append({'url':current,'method':'POST' if cfg else 'GET','endpoint':BASE+'/products/blockitems' if cfg else current,'parameters':{**cfg['payload'],'page':page} if cfg else {},**parsed['pagination'],'vinyl':len(parsed['records']),'excluded':len(parsed['excluded']),'sha256':parsed['listing_sha256']})
                    progress['seen_ids']+=ids;progress['next']=parsed['next_url'];progress['complete']=not parsed['next_url'] and (category=='home' or not parsed['pagination']['bounded_collection'])
                    # Static collections have an unproven cap; never claim complete coverage.
                    processed+=1;save(path,state);print(json.dumps({'category':category,'page':parsed['pagination']['page'],'unique_vinyl':len(state['records']),'requests':len(client.requests)}),flush=True)
                if processed>=max_pages:break
        if mode=='details':
            due=[r for r in state['records'].values() if r.get('detail_parser_revision')!=DETAIL_REVISION or not r.get('detail_next_at') or r['detail_next_at']<=now()]
            due.sort(key=lambda r:(0 if r.get('detail_observed_at') and r.get('detail_parser_revision')!=DETAIL_REVISION else 1 if r.get('ean_status')=='pending' else 2,r.get('detail_observed_at',''),r['source_product_id']))
            for row in due[:detail_limit]:
                rid=row['source_product_id'];html=client.get(row['source_url'])
                try:state['records'][rid]=enrich(row,html)
                except ValueError as exc:
                    state['records'][rid]={**row,'ean':'','gtin14':'','ean_status':'quarantine','detail_parser_revision':DETAIL_REVISION,'reason':str(exc),'detail_observed_at':now(),'detail_next_at':(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()}
                save(path,state);print(json.dumps({'release_id':rid,'ean_status':state['records'][rid]['ean_status']}),flush=True)
    except Exception as exc:
        state['error']=str(exc);raise
    finally:
        state['requests']+=client.requests if client is not None else [];state['updated_at']=now();save(path,state)
        rows=list(state['records'].values());out=path.parent;out.mkdir(parents=True,exist_ok=True)
        with (out/'products.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(rows)
        summary={'shop_id':SHOP_ID,'database_writes':False,'unique_vinyl_releases':len(rows),'verified_eans':sum(r.get('ean_status')=='verified' for r in rows),'valid_listing_prices':sum(bool(r.get('price')) for r in rows),'availability':{a:sum(r.get('availability')==a for r in rows) for a in ('in_stock','supplier_order','preorder','out_of_stock','unknown')},'categories':state['categories'],'requests':len(state['requests']),'error':state['error'],'catalogue_complete':bool(len(state['categories'])==len(GENRES)+len(COLLECTIONS)+1 and all(c['complete'] for c in state['categories'].values())),'deletions':0}
        save(out/'summary.json',summary)
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=('discovery','prices','details'),default='discovery');p.add_argument('--state',default='output/velvetdelft/state.json');p.add_argument('--max-pages',type=int,default=25);p.add_argument('--detail-limit',type=int,default=100);p.add_argument('--refresh',action='store_true');a=p.parse_args()
    if not 1<=a.max_pages<=1000 or not 1<=a.detail_limit<=250:p.error('Pages 1..1000, detail limit 1..250')
    collect(a.mode,a.state,a.max_pages,a.detail_limit,refresh=a.refresh)
if __name__=='__main__':main()
