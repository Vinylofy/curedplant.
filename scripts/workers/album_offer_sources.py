"""Shop-independent source verification for the private album-offer queue.
Only source evidence is written here; album matching/publication stays in Vinylofy.
"""
from datetime import datetime,timezone,timedelta
from decimal import Decimal
import hashlib
import html as html_module
import ipaddress
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urljoin
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from scripts.importers.common import strict_normalize_gtin

UA='VinylofyAlbumSource/1.0 (https://vinylofy.com; contact: info@vinylofy.com)'

def now():return datetime.now(timezone.utc)
def text(v):return re.sub(r'\s+',' ',html_module.unescape(v)).strip() if isinstance(v,str) else ''
def norm(v):return re.sub(r'[^\w]+',' ',text(v).casefold()).strip()

def approved_url(url,domain):
    p=urlsplit(url);host=(p.hostname or '').removeprefix('www.')
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment or host!=domain.removeprefix('www.') or '.' not in host or host.endswith(('.local','.internal','.localhost')):raise ValueError('unapproved_source_url')
    try:ipaddress.ip_address(host)
    except ValueError:return url
    raise ValueError('ip_source_forbidden')

class Transport:
    def __init__(self,domain):
        self.domain=domain;self.session=requests.Session();self.session.headers['User-Agent']=UA
        self.last=None;self.delay=2.;self.robot=None;self.requests=[]
    def get(self,url,_redirects=0):
        approved_url(url,self.domain)
        if self.robot and not self.robot.can_fetch(UA,url):raise ValueError('robots_disallow')
        if self.last is not None:time.sleep(max(0,self.delay-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        with self.session.get(url,timeout=20,stream=True,allow_redirects=False) as r:
            if r.status_code in (301,302,303,307,308):
                if _redirects>=2:raise ValueError('source_redirect_limit')
                target=urljoin(url,r.headers.get('Location',''))
                approved_url(target,self.domain)
                self.requests.append({'url':url,'status':r.status_code,'location':target})
                return self.get(target,_redirects+1)
            if r.status_code!=200:raise RuntimeError('HTTP_'+str(r.status_code))
            data=r.raw.read(2000001,decode_content=True)
            if len(data)>2000000:raise ValueError('source_size_limit')
            body=data.decode(r.encoding or 'utf-8',errors='replace')
            if re.search(r'cf-chl-|challenge-platform|<title>Just a moment',body,re.I):raise RuntimeError('ACCESS_CHALLENGE')
            self.requests.append({'url':url,'sha256':hashlib.sha256(data).hexdigest()});return body
    def start(self,url):
        robot_url='https://'+urlsplit(url).netloc+'/robots.txt'
        try:body=self.get(robot_url)
        except RuntimeError as e:
            if str(e)!='HTTP_404':raise
            body=''
        self.robot=RobotFileParser();self.robot.parse(body.splitlines())
        delay=self.robot.crawl_delay(UA) or self.robot.crawl_delay('*') or 0
        if delay>30:raise ValueError('robots_delay_requires_review')
        self.delay=max(self.delay,delay)
    def close(self):self.session.close()

def json_products(html):
    soup=BeautifulSoup(html,'html.parser');found=[]
    def walk(v):
        if isinstance(v,list):
            for item in v:walk(item)
        elif isinstance(v,dict):
            types=v.get('@type',[]);types=[types] if isinstance(types,str) else types
            if 'Product' in types:found.append(v)
            if '@graph' in v:walk(v['@graph'])
    for node in soup.select('script[type="application/ld+json"]'):
        try:walk(json.loads(node.string or node.get_text()))
        except (ValueError,TypeError):continue
    return soup,found

def same_page(a,b):
    x,y=urlsplit(a),urlsplit(b)
    return (x.hostname or '').removeprefix('www.')==(y.hostname or '').removeprefix('www.') and x.path.rstrip('/')==y.path.rstrip('/')

def availability(v):
    return {'InStock':'in_stock','PreOrder':'preorder','PreSale':'preorder','OutOfStock':'out_of_stock','SoldOut':'out_of_stock'}.get(str(v).rsplit('/',1)[-1],'unknown')

def verify_source(row,transport):
    url=row['product_url'];domain=row['shop_domain'];approved_url(url,domain)
    html=transport.get(url);soup,nodes=json_products(html)
    canonical=soup.select_one('link[rel="canonical"]');canonical_url=urljoin(url,canonical.get('href','')) if canonical else url
    approved_url(canonical_url,domain)
    own=[p for p in nodes if (p.get('url') or p.get('@id')) and (same_page(urljoin(url,str(p.get('url') or p['@id']).split('#')[0]),url) or same_page(urljoin(url,str(p.get('url') or p['@id']).split('#')[0]),canonical_url))]
    if len(own)!=1:raise ValueError('own_structured_product_unproven')
    product=own[0];name=text(product.get('name'));area=soup.select_one('[itemtype="https://schema.org/Product"], .product-page, main, article');h1=(area or soup).select_one('h1')
    if not name or not h1 or norm(name)!=norm(h1.get_text(' ',strip=True)):raise ValueError('own_product_title_unproven')
    description=name+' '+text(product.get('description'))
    conditions=[str(product.get('itemCondition',''))]
    offers=product.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
    offers=[o for o in offers if isinstance(o,dict) and o.get('price') is not None]
    if not offers:raise ValueError('own_article_price_unproven')
    variant=parse_qs(urlsplit(url).query).get('variant',[None])[0]
    if variant:
        offers=[o for o in offers if parse_qs(urlsplit(str(o.get('url',''))).query).get('variant',[None])[0]==variant]
    if len(offers)!=1:raise ValueError('selected_variant_offer_ambiguous')
    offer=offers[0];conditions.append(str(offer.get('itemCondition','')))
    if any(c and not c.endswith('/NewCondition') for c in conditions) or re.search(r'\b(?:used\s+(?:vinyl|record|lp)|second[- ]hand|pre[- ]owned|tweedehands|2e\s*hands|gebraucht|media condition|sleeve condition)\b',description,re.I):raise ValueError('used_or_ambiguous_condition')
    if not re.search(r'\b(?:[2-9]?LP|VINYL|[712][02]?[- ]?INCH)\b',name+' '+str(row['source_input'].get('format','')),re.I) or re.search(r'\b(?:CD|DVD|CASSETTE|BUNDLE)\b',name,re.I):raise ValueError('vinyl_format_unproven')
    price=Decimal(str(offer['price']));currency=offer.get('priceCurrency');stock=availability(offer.get('availability'))
    if not price.is_finite() or price<=0 or not re.fullmatch(r'[A-Z]{3}',str(currency)) or stock=='unknown':raise ValueError('price_currency_stock_unproven')
    codes=[]
    for p in (product,offer):
        for key in ('gtin','gtin8','gtin12','gtin13','gtin14'):
            if p.get(key) not in (None,''):
                code=strict_normalize_gtin(str(p[key]))
                if not code:raise ValueError('invalid_structured_barcode')
                codes.append(code)
    # Inspect labelled specification rows only inside the own product area.
    # Recommendation cards, headers and footers cannot supply this product's EAN.
    area=soup.select_one('[itemtype="https://schema.org/Product"], .product-page, main, article')
    if area:
        area=BeautifulSoup(str(area),'html.parser')
        for other in area.select('.related, .related-products, .products, .product-recommendations, nav, header, footer'):other.decompose()
        for spec_row in area.select('table tr'):
            cells=spec_row.find_all(['th','td'],recursive=False)
            if len(cells)>=2 and re.fullmatch(r'(?:ean|barcode|upc|gtin(?:8|12|13|14)?)',text(cells[0].get_text()).rstrip(':'),re.I):
                value=text(cells[1].get_text())
                if value:
                    code=strict_normalize_gtin(value)
                    if not code:raise ValueError('invalid_own_specification_barcode')
                    codes.append(code)
    # Shopify's own public product JSON is a catalogue source, not a SKU guess.
    # Multi-variant products must have an explicitly selected variant.
    if re.fullmatch(r'/products/[a-zA-Z0-9-]+/?',urlsplit(url).path):
        base='https://'+urlsplit(url).netloc+urlsplit(url).path.rstrip('/')
        data=json.loads(transport.get(base+'.js'));variants=data.get('variants',[])
        selected=[v for v in variants if str(v.get('id'))==variant] if variant else variants
        if len(selected)!=1:raise ValueError('catalogue_variant_ambiguous')
        selected=selected[0]
        if type(selected.get('price')) is not int or Decimal(selected['price'])/100!=price:raise ValueError('catalogue_html_price_mismatch')
        if type(selected.get('available')) is not bool or (selected['available'] and stock!='in_stock') or (not selected['available'] and stock=='in_stock'):raise ValueError('catalogue_availability_requires_review')
        raw=selected.get('barcode')
        if raw not in (None,''):
            code=strict_normalize_gtin(str(raw))
            if not code:raise ValueError('invalid_catalogue_barcode')
            codes.append(code)
        listing_at=now().isoformat();price_basis='public_catalogue_json_crosschecked_own_html'
    else:
        if not area:raise ValueError('own_specification_scope_unproven')
        source=row['source_input'];listing_at=source.get('listing_observed_at','')
        if source.get('price_source') not in ('listing','catalogue') or Decimal(str(source.get('price')))!=price or source.get('currency')!=currency:raise ValueError('fresh_listing_price_required')
        age=(now()-datetime.fromisoformat(listing_at)).total_seconds()
        if not 0<=age<=48*3600:raise ValueError('listing_price_stale')
        price_basis='fresh_listing_crosschecked_own_html'
    if len(set(codes))>1:raise ValueError('conflicting_source_barcodes')
    artist=product.get('byArtist') or product.get('artist')
    artist=artist.get('name') if isinstance(artist,dict) else artist
    if not isinstance(artist,str):artist=None
    label=name if not artist or norm(name).startswith(norm(artist)+' ') else artist+' '+name
    return {'status':'validated','route':'EAN' if codes else 'ARTIST_TITLE','ean_status':'EAN_AVAILABLE' if codes else 'EAN_NOT_FOUND',
      'gtin14':codes[0] if codes else None,'domain':domain,'source_url':url,'canonical_url':canonical_url,
      'source_product_id':row.get('source_product_id'),'source_title':name,'artist':artist,'label':label,
      'price':str(price),'currency':currency,'availability':stock,'format_status':'vinyl','condition_status':'new',
      'condition_basis':'explicit_new' if any(conditions) else 'existing_no_used_signal_policy',
      'observed_at':now().isoformat(),'listing_observed_at':listing_at,'price_basis':price_basis,
      'source_sha256':hashlib.sha256(html.encode()).hexdigest(),'requests':transport.requests}

def claim(conn,limit):
    token=str(uuid.uuid4())
    with conn.transaction(),conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""with due as(select id from public.album_offer_queue
          where status in ('pending_source','source_retry','published','awaiting_market') and next_attempt_at<=now()
            and (lease_until is null or lease_until<now())
          order by next_attempt_at,updated_at,id for update skip locked limit %s)
          update public.album_offer_queue q set claim_token=%s,lease_until=now()+interval '30 minutes',source_attempts=source_attempts+1
          from due where due.id=q.id returning q.*,(select domain from shops where id=q.shop_id) as shop_domain""",(limit,token))
        return cur.fetchall(),token

def collect(conn,limit=50):
    rows,token=claim(conn,limit);transports={};stopped=set();summary={};started=time.monotonic()
    try:
        for row in rows:
            if time.monotonic()-started>20*60:break
            domain=row['shop_domain'];record={};status='source_review';reason=None
            try:
                if domain in stopped:raise RuntimeError('shop_access_paused')
                if domain not in transports:
                    transports[domain]=Transport(domain);transports[domain].start(row['product_url'])
                record=verify_source(row,transports[domain]);status='ean_routed' if record['route']=='EAN' else 'pending_match'
            except requests.RequestException:status='source_retry';reason='source_network_failure';stopped.add(domain)
            except RuntimeError as error:status='source_retry';reason=str(error);stopped.add(domain)
            except (ValueError,TypeError,KeyError,ArithmeticError) as error:reason=str(error)
            same_identity=bool(record) and norm(record.get('label',''))==norm(row['source_record'].get('label',''))
            if same_identity and row.get('offer_id') and row['match_result'].get('status')=='matched' and record.get('route')=='ARTIST_TITLE':
                status='published'
            with conn.transaction(),conn.cursor() as cur:
                cur.execute('select claim_token from public.album_offer_queue where id=%s for update',(row['id'],))
                owned=cur.fetchone()
                if not owned or str(owned[0])!=token:continue
                if same_identity and record.get('status')=='validated' and record.get('route')=='ARTIST_TITLE' and row.get('offer_id'):
                    cur.execute("""update public.album_alternative_offers set price=%s,currency=%s,availability=%s,
                      last_seen_at=%s,last_price_checked_at=%s where id=%s and shop_id=%s and promotion_status='none'
                      and last_price_checked_at<=%s""",(record['price'],record['currency'],record['availability'],record['observed_at'],record['listing_observed_at'],row['offer_id'],row['shop_id'],record['listing_observed_at']))
                if record.get('route')=='EAN':
                    raw_shop=row['source_input'].get('raw_shop_id')
                    if not raw_shop:raise ValueError('EAN delivery needs the existing raw shop mapping')
                    raw_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'album-source-ean:'+str(row['id'])+':'+record['gtin14']))
                    payload={**record,'origin':'album_source_ean_discovery','price_source':'listing',
                      'listing_seen_at':record['listing_observed_at'],'format':'LP','artist_raw':record.get('artist')}
                    cur.execute("""insert into public.raw_shop_scrapes(id,run_id,shop_id,source_url,source_product_id,title_raw,
                      ean_raw,price_raw,availability_raw,image_url_raw,payload)
                      values(%s,null,%s,%s,%s,%s,%s,%s,%s,null,%s) on conflict(id) do nothing""",
                      (raw_id,raw_shop,row['product_url'],row['source_product_id'],record['source_title'],record['gtin14'],record['price'],record['availability'],Jsonb(payload)))
                    record['ean_destination']='raw_shop_scrapes'
                if record.get('route')=='EAN' and row.get('offer_id'):
                    cur.execute("update public.album_alternative_offers set ean_status='EAN_AVAILABLE',promotion_status='pending' where id=%s and promotion_status='none'",(row['offer_id'],))
                cur.execute("""update public.album_offer_queue set source_record=case when %s::jsonb->>'status'='validated' then %s::jsonb else source_record end,status=%s,reason=%s,
                  match_result=case when %s then match_result else '{}'::jsonb end,
                  manual_group=case when %s then manual_group else null end,
                  candidates=case when %s then candidates else '[]'::jsonb end,
                  next_attempt_at=now()+case when %s='source_retry' then interval '6 hours' when %s='published' then interval '24 hours' else interval '0 hours' end,
                  claim_token=null,lease_until=null,updated_at=now() where id=%s and claim_token=%s""",
                  (Jsonb(record),Jsonb(record),status,reason,same_identity or not record,same_identity or not record,same_identity or not record,status,status,row['id'],token))
            summary[status]=summary.get(status,0)+1
        return {'processed':sum(summary.values()),'claimed':len(rows),'statuses':summary}
    finally:
        conn.execute('update public.album_offer_queue set claim_token=null,lease_until=null where claim_token=%s',(token,))
        for transport in transports.values():transport.close()

def main():
    import os,argparse
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=50);args=p.parse_args()
    if not 1<=args.limit<=50:raise ValueError('Source pilot limit is 1..50')
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,connect_timeout=20,prepare_threshold=None) as conn:
        report=collect(conn,args.limit) if conn.execute("select to_regclass('public.album_offer_queue')").fetchone()[0] else {'status':'not_installed','processed':0}
    path=Path('output/album-offer-sources/result.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
