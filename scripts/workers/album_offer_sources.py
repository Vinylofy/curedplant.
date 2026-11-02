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

REVISION=5
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

def source_label(name,artist):
    title=re.sub(r'^(?:[1-9]?LP|VINYL)\s*[-–—:]\s*','',name,flags=re.I)
    if artist:
        title=re.sub(r'^'+re.escape(artist)+r'(?:\s*[-–—:]\s*|\s+)','',title,flags=re.I)
        title=re.sub(r'\s*[-–—]\s*'+re.escape(artist)+r'$','',title,flags=re.I)
        return artist+' '+title
    return title

def heading_key(value):
    value=re.sub(r'\s*[\[(](?:(?:red|blue|green|black|white|clear|colou?red|transparent|pink|purple|marble)\s+vinyl|[1-9]?LP|\d{2,3}\s*g)[\])]\s*$','',value,flags=re.I)
    return norm(value)

def expanded_offer(offer):
    if offer.get('price') is not None:return offer
    specs=offer.get('priceSpecification',[]);specs=[specs] if isinstance(specs,dict) else specs
    specs=[s for s in specs if isinstance(s,dict) and s.get('price') is not None and not str(s.get('priceType','')).endswith(('StrikethroughPrice','ListPrice'))]
    sales=[s for s in specs if str(s.get('priceType','')).endswith('SalePrice')]
    selected=sales or specs
    if len(selected)!=1:return offer
    return {**offer,'price':selected[0]['price'],'priceCurrency':selected[0].get('priceCurrency') or offer.get('priceCurrency')}

def visible_article_prices(area,domain):
    found=set()
    for node in area.select('[itemprop="price"][content], .summary .price .woocommerce-Price-amount, .summary .product-price-wrapper .price-container .woocommerce-Price-amount, .page__product__price .incl-price .ShowProductQuickOrderPrice'):
        if node.find_parent('del'):continue
        value=node.get('content') or node.get_text(' ',strip=True)
        match=re.fullmatch(r'\s*(?:€\s*)?([0-9]{1,5}(?:[.,][0-9]{2})?)\s*(?:€)?\s*',value)
        if match:found.add(Decimal(match.group(1).replace(',','.')))
    return found

def verify_source(row,transport):
    url=row['product_url'];domain=row['shop_domain'];approved_url(url,domain)
    html=transport.get(url);soup,nodes=json_products(html)
    if domain.removeprefix('www.')=='atube-highfidelity.nl':
        from scripts.scrapers.atubehighfidelity import verify_album_source
        return {**verify_album_source(html,row),'requests':transport.requests}
    if domain.removeprefix('www.')=='northendhaarlem.nl':
        from scripts.workers.northend_album_pilot import parse_source,source_identity,canonical_target
        from scripts.scrapers.usf.jobs.detail_northendhaarlem import parse_detail_page
        source=row['source_input'];stamp=now().isoformat()
        current=parse_detail_page(html,listing_payload={'title_raw':source.get('title_raw'),'price':source.get('price')})
        price=current.get('detail_price_seen')
        if price is None:raise ValueError('own_article_price_unproven')
        item={'source_url':url,'source_product_id':source_identity(url),'title_raw':source.get('title_raw') or current.get('title_raw'),
              'listing_price':str(price),'currency':'EUR','listing_observed_at':stamp}
        target=canonical_target(html,item)
        result=parse_source(html,item,stamp,canonical_body=transport.get(target) if target else None)
        price_basis='verified_visible_article_price_fallback';price_at=stamp
        if source.get('price_source') in ('listing','catalogue') and source.get('listing_observed_at'):
            try:fresh=0<=(now()-datetime.fromisoformat(source['listing_observed_at'])).total_seconds()<=48*3600
            except (ValueError,TypeError):fresh=False
            if fresh:
                if Decimal(str(source.get('price')))!=Decimal(result['price']):raise ValueError('listing_detail_price_conflict')
                price_basis='fresh_listing_crosschecked_own_html';price_at=source['listing_observed_at']
        return {**result,'domain':domain,'artist':result.get('source_artist'),'label':source_label(result['source_title'],result.get('source_artist')),
          'listing_observed_at':price_at,'price_basis':price_basis,'requests':transport.requests,
          'ean_check_scope':'own North End product specification labels, verified same-title canonical aliases; no SKU inference'}
    canonical=soup.select_one('link[rel="canonical"]');canonical_url=urljoin(url,canonical.get('href','')) if canonical else url
    approved_url(canonical_url,domain)
    def own_url(p):
        subject=p.get('subjectOf') if isinstance(p.get('subjectOf'),dict) else {}
        return p.get('url') or p.get('@id') or subject.get('url')
    own=[p for p in nodes if own_url(p) and any(same_page(urljoin(url,str(own_url(p)).split('#')[0]),u) for u in (url,canonical_url))]
    if len(own)!=1:raise ValueError('own_structured_product_unproven')
    product=own[0];name=text(product.get('name'))
    area=soup.select_one('[itemtype="https://schema.org/Product"], [itemtype="http://schema.org/Product"], .product-page, .single-product .product, main, article, div.content')
    h1=(area or soup).select_one('h1')
    if not name or not h1:raise ValueError('own_product_title_unproven')
    properties={}
    props=product.get('additionalProperty',[]);props=[props] if isinstance(props,dict) else props
    for p in props:
        if isinstance(p,dict):properties[text(p.get('name')).casefold()]=text(p.get('value'))
    own_area=BeautifulSoup(str(area),'html.parser') if area else None
    if own_area:
        for other in own_area.select('.related, .related-products, .related-product-card, .RelatedProducts, .products, .product-recommendations, .upsells, .cross-sells, [itemprop="isSimilarTo"], [itemprop="isRelatedTo"], nav, header, footer'):other.decompose()
        for spec_row in own_area.select('table tr'):
            cells=spec_row.find_all(['th','td'],recursive=False)
            if len(cells)>=2:properties[text(cells[0].get_text()).casefold().rstrip(':')]=text(cells[1].get_text(' ',strip=True))
    subject=product.get('subjectOf') if isinstance(product.get('subjectOf'),dict) else {}
    artist=product.get('byArtist') or product.get('artist') or subject.get('byArtist')
    if isinstance(artist,list):
        artist=' & '.join(a['name'] for a in artist if isinstance(a,dict) and isinstance(a.get('name'),str)) or None
    if isinstance(artist,dict):artist=artist.get('name')
    if not isinstance(artist,str):artist=next((properties[k] for k in ('artist','artiest','uitvoerende') if properties.get(k)),None)
    heading=text(h1.get_text(' ',strip=True));expected=source_label(name,artist)
    trimmed_heading=re.sub(r'\s+(?:(?:auf|on)\s+)?[1-9]?LP\s*$','',heading,flags=re.I)
    if heading_key(name)!=heading_key(heading) and (not artist or heading_key(expected)!=heading_key(trimmed_heading)):
        raise ValueError('own_product_title_unproven')
    description=name+' '+text(product.get('description'))
    conditions=[str(product.get('itemCondition',''))]
    offers=product.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
    offers=[expanded_offer(o) for o in offers if isinstance(o,dict)]
    offers=[o for o in offers if o.get('price') is not None]
    if not offers:raise ValueError('own_article_price_unproven')
    variant=parse_qs(urlsplit(url).query).get('variant',[None])[0]
    if variant:offers=[o for o in offers if parse_qs(urlsplit(str(o.get('url',''))).query).get('variant',[None])[0]==variant]
    if len(offers)!=1:raise ValueError('selected_variant_offer_ambiguous')
    offer=offers[0];conditions.append(str(offer.get('itemCondition','')))
    if any(c and not c.endswith('/NewCondition') for c in conditions) or re.search(r'\b(?:used\s+(?:vinyl|record|lp)|second[- ]hand|pre[- ]owned|tweedehands|2e\s*hands|gebraucht|media condition|sleeve condition)\b',description,re.I):raise ValueError('used_or_ambiguous_condition')
    catalogue=None
    catalogue_format=''
    is_shopify=bool(re.fullmatch(r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:collections/[a-zA-Z0-9-]+/)?products/[a-zA-Z0-9-]+/?',urlsplit(url).path))
    def load_catalogue():
        base='https://'+urlsplit(url).netloc+urlsplit(url).path.rstrip('/')
        data=json.loads(transport.get(base+'.js'))
        if norm(text(data.get('title')))!=norm(name):raise ValueError('catalogue_html_title_mismatch')
        return data
    formats=' '.join(str(v) for v in [name,product.get('category',''),product.get('description',''),row['source_input'].get('format','')]+[properties.get(k,'') for k in ('formaat','format','media type','inhoud','size','drager')])
    if is_shopify and not re.search(r'\b(?:[1-9]?LP|VINYL|(?:7|10|12)[- ]?INCH)\b',formats,re.I):
        catalogue=load_catalogue()
        # The own public catalogue explicitly identifies the carrier even when
        # Product JSON-LD has no category. Never infer vinyl from the store alone.
        carrier=text(catalogue.get('type'))
        if re.fullmatch(r'(?:[1-9](?:X)?\s*)?LP|VINYL',carrier,re.I):catalogue_format='LP'
    formats+=' '+catalogue_format
    if not re.search(r'\b(?:[1-9]?LP|VINYL|(?:7|10|12)[- ]?INCH)\b',formats,re.I) or re.search(r'\b(?:CD|DVD|CASSETTE|BUNDLE)\b',name,re.I):raise ValueError('vinyl_format_unproven')
    price=Decimal(str(offer['price']));currency=str(offer.get('priceCurrency','')).upper();stock=availability(offer.get('availability'))
    if not price.is_finite() or price<=0 or not re.fullmatch(r'[A-Z]{3}',currency) or stock=='unknown':raise ValueError('price_currency_stock_unproven')
    codes=[]
    for p in (product,offer):
        for field in ('gtin','gtin8','gtin12','gtin13','gtin14'):
            if p.get(field) not in (None,''):
                code=strict_normalize_gtin(str(p[field]))
                if not code:raise ValueError('invalid_structured_barcode')
                codes.append(code)
    for field,value in properties.items():
        if re.fullmatch(r'(?:ean(?:\s*code)?|barcode|upc|gtin(?:8|12|13|14)?)',field) and value:
            code=strict_normalize_gtin(value)
            if not code:raise ValueError('invalid_own_specification_barcode')
            codes.append(code)
    for match in re.finditer(r'(?<![A-Za-z])(?:EAN(?:\s*Code)?|Barcode|UPC|GTIN(?:8|12|13|14)?)\s*[:：#]\s*([0-9][0-9 -]{6,18}[0-9])',text(product.get('description')),re.I):
        code=strict_normalize_gtin(match.group(1))
        if not code:raise ValueError('invalid_own_description_barcode')
        codes.append(code)
    if len(set(codes))>1:raise ValueError('conflicting_source_barcodes')
    if is_shopify:
        catalogue=catalogue if catalogue is not None else load_catalogue()
        variants=catalogue.get('variants',[])
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
        if not own_area:raise ValueError('own_specification_scope_unproven')
        source=row['source_input'];listing_at=source.get('listing_observed_at','')
        fresh=False
        try:fresh=source.get('price_source') in ('listing','catalogue') and 0<=(now()-datetime.fromisoformat(listing_at)).total_seconds()<=48*3600
        except (TypeError,ValueError):pass
        if fresh:
            if Decimal(str(source.get('price')))!=price or source.get('currency')!=currency:raise ValueError('listing_detail_price_conflict')
            price_basis='fresh_listing_crosschecked_own_html'
        else:
            if visible_article_prices(own_area,domain)!={price}:raise ValueError('fresh_listing_or_visible_own_price_required')
            listing_at=now().isoformat();price_basis='verified_visible_article_price_fallback'
    if len(set(codes))>1:raise ValueError('conflicting_source_barcodes')
    return {'status':'validated','route':'EAN' if codes else 'ARTIST_TITLE','ean_status':'EAN_AVAILABLE' if codes else 'EAN_NOT_FOUND',
      'gtin14':codes[0] if codes else None,'domain':domain,'source_url':url,'canonical_url':canonical_url,
      'source_product_id':row.get('source_product_id'),'source_title':name,'artist':artist,'label':expected,
      'price':str(price),'currency':currency,'availability':stock,'format_status':'vinyl','condition_status':'new',
      'condition_basis':'explicit_new' if any(conditions) else 'existing_no_used_signal_policy',
      'observed_at':now().isoformat(),'listing_observed_at':listing_at,'price_basis':price_basis,
      'source_sha256':hashlib.sha256(html.encode()).hexdigest(),'requests':transport.requests,
      'ean_check_scope':'selected public catalogue barcode, own Product JSON-LD, labelled own specifications and description; no SKU inference'}

def claim(conn,limit):
    token=str(uuid.uuid4())
    with conn.transaction(),conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select pg_advisory_xact_lock(hashtextextended('album_offer_queue_capacity_v1',0))")
        cur.execute("select count(*) as active from album_offer_queue where (status in ('pending_source','pending_match','ready') or (status in ('source_retry','match_retry') and next_attempt_at<=now())) or lease_until>now()")
        capacity=max(0,50-cur.fetchone()['active'])
        cur.execute("""with revisited as(select id from public.album_offer_queue where status='source_review'
          and coalesce(source_input->>'validator_revision','0')::integer<%s
          and next_attempt_at<=now() and (lease_until is null or lease_until<now()) order by updated_at,id limit %s),
          due as(select id from public.album_offer_queue
          where (status in ('pending_source','source_retry','published','awaiting_market') or id in(select id from revisited)) and next_attempt_at<=now()
            and (lease_until is null or lease_until<now())
          order by (status='source_review'),next_attempt_at,updated_at,id for update skip locked limit %s)
          update public.album_offer_queue q set claim_token=%s,lease_until=now()+interval '30 minutes',source_attempts=source_attempts+1
          from due where due.id=q.id returning q.*,(select domain from shops where id=q.shop_id) as shop_domain""",(REVISION,capacity,limit,token))
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
            except RuntimeError as error:
                if str(error) in ('HTTP_404','HTTP_410'):status='source_review';reason='source_url_not_found'
                else:status='source_retry';reason=str(error);stopped.add(domain)
            except (ValueError,TypeError,KeyError,ArithmeticError) as error:reason=str(error)
            same_identity=bool(record) and norm(record.get('label',''))==norm(row['source_record'].get('label',''))
            if same_identity and row.get('offer_id') and row['match_result'].get('status')=='matched' and record.get('route')=='ARTIST_TITLE':
                status='published'
            with conn.transaction(),conn.cursor() as cur:
                cur.execute('select claim_token from public.album_offer_queue where id=%s for update',(row['id'],))
                owned=cur.fetchone()
                if not owned or str(owned[0])!=token:continue
                if same_identity and record.get('price_basis')=='verified_visible_article_price_fallback' and row.get('offer_id'):
                    cur.execute('select price,last_price_checked_at,metadata from album_alternative_offers where id=%s for update',(row['offer_id'],))
                    prior=cur.fetchone()
                    if prior and prior[1] and (now()-prior[1]).total_seconds()<48*3600 and prior[2].get('price_basis')!='verified_visible_article_price_fallback':
                        if Decimal(record['price'])!=prior[0]:status='source_review';reason='listing_detail_price_conflict'
                        else:record['listing_observed_at']=prior[1].isoformat();record['price_basis']=prior[2].get('price_basis') or 'preserved_existing_listing'
                if status!='source_review' and same_identity and record.get('status')=='validated' and record.get('route')=='ARTIST_TITLE' and row.get('offer_id'):
                    cur.execute("""update public.album_alternative_offers set price=%s,currency=%s,availability=%s,
                      last_seen_at=%s,last_price_checked_at=%s,metadata=metadata||%s where id=%s and shop_id=%s and promotion_status='none'
                      and last_price_checked_at<=%s""",(record['price'],record['currency'],record['availability'],record['observed_at'],record['listing_observed_at'],Jsonb({'price_basis':record.get('price_basis')}),row['offer_id'],row['shop_id'],record['listing_observed_at']))
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
                  next_attempt_at=now()+case when %s='source_retry' then interval '6 hours' when %s='published' then interval '20 hours' else interval '0 hours' end,
                  source_input=source_input||jsonb_build_object('validator_revision',%s::integer),
                  claim_token=null,lease_until=null,updated_at=now() where id=%s and claim_token=%s""",
                  (Jsonb(record),Jsonb(record),status,reason,same_identity or not record,same_identity or not record,same_identity or not record,status,status,REVISION,row['id'],token))
            summary[status]=summary.get(status,0)+1
            print(json.dumps({'queue_id':str(row['id']),'shop':domain,'status':status,'processed':sum(summary.values())}),flush=True)
        return {'processed':sum(summary.values()),'claimed':len(rows),'statuses':summary}
    finally:
        conn.execute('update public.album_offer_queue set claim_token=null,lease_until=null where claim_token=%s',(token,))
        for transport in transports.values():transport.close()

def verify_capture(path):
    """Replay a repository-controlled Linux capture without renewing its timestamp.

    This is an explicit manual recovery path. It does not claim the scheduled
    GitHub runner can access a shop that blocks that runner.
    """
    captured=json.loads(path.read_text());raw=captured['raw'];stamp=datetime.fromisoformat(captured['observed_at'])
    if not -300<=(now()-stamp).total_seconds()<=24*3600:raise ValueError('stale_capture')
    class Replay:
        requests=[]
        def get(self,url):
            approved_url(url,raw['domain'])
            response=next((r for r in captured['responses'] if r['url']==url),None)
            if response is None:raise ValueError('capture_response_missing')
            body=response['body'];digest=hashlib.sha256(body.encode()).hexdigest()
            if digest!=response['sha256']:raise ValueError('capture_hash_mismatch')
            self.requests.append({'url':url,'sha256':digest});return body
    source_input=captured['source_input']
    row={'product_url':captured['product_url'],'shop_domain':raw['domain'],'source_product_id':raw['source_product_id'],'source_input':source_input}
    result=verify_source(row,Replay())
    # The parser observes a replay now; its public freshness is the actual capture.
    result['observed_at']=stamp.isoformat()
    if datetime.fromisoformat(result['listing_observed_at'])>stamp:result['listing_observed_at']=stamp.isoformat()
    result['capture_provenance']={'origin':'managed_linux_manual_recovery','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'validator_revision':REVISION,'observed_at':stamp.isoformat()}
    return {'records':[{'raw':{k:raw[k] for k in ('id','source_url','source_product_id','title_raw','target_shop_id','domain')},'source_input':source_input,'record':result}], 'capture_provenance':result['capture_provenance']}

def main():
    import os,argparse
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=50);p.add_argument('--verify-capture');p.add_argument('--capture-output');args=p.parse_args()
    if args.verify_capture:
        result=verify_capture(Path(args.verify_capture));path=Path(args.capture_output or 'output/album-offer-sources/validated-capture.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'status':'verified_capture','records':len(result['records'])}));return
    if not 1<=args.limit<=50:raise ValueError('Source pilot limit is 1..50')
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True,connect_timeout=20,prepare_threshold=None) as conn:
        if conn.execute("select to_regclass('public.album_offer_queue')").fetchone()[0]:
            # Repair the initial classifier's per-shop pause after a missing
            # product page. Real access denials remain untouched.
            conn.execute("""with affected as materialized(select distinct shop_id from album_offer_queue
              where status='source_retry' and reason in ('HTTP_404','HTTP_410'))
              update album_offer_queue q set status='pending_source',reason='missing_page_retry_classifier_fixed',next_attempt_at=now(),updated_at=now()
              where q.status='source_retry' and q.reason in ('HTTP_404','HTTP_410','shop_access_paused')
                and q.shop_id in(select shop_id from affected) and (q.lease_until is null or q.lease_until<now())
                and not exists(select 1 from album_offer_queue denied where denied.shop_id=q.shop_id and denied.status='source_retry'
                  and denied.reason in ('HTTP_401','HTTP_403','HTTP_429','ACCESS_CHALLENGE') and denied.next_attempt_at>now())""")
        report=collect(conn,args.limit) if conn.execute("select to_regclass('public.album_offer_queue')").fetchone()[0] else {'status':'not_installed','processed':0}
    path=Path('output/album-offer-sources/result.json');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
