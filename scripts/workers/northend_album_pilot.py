"""Manual, read-only North End artist/album source pilot. Maximum 25 products.
No DB operations, EAN publication, retries after access denial or full crawls.
"""
from datetime import datetime,timezone
from decimal import Decimal
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from scripts.scrapers.usf.jobs.detail_northendhaarlem import parse_detail_page,product_scope,clean,normalize_ean

ROOT=Path(__file__).resolve().parents[2]
UA='VinylofyAlbumPilot/1.0'


def source_identity(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in ('northendhaarlem.nl','www.northendhaarlem.nl') or p.username or p.password or p.port not in (None,443):raise ValueError('Unreviewed source URL')
    m=re.search(r'^/a-(\d+)(?:/|$)',p.path)
    if not m:raise ValueError('Not a North End product URL')
    return m.group(1)


def parse_source(body,item,observed_at):
    soup=BeautifulSoup(body,'html.parser');scope=product_scope(soup)
    if scope is None:raise ValueError('Own product scope absent; possible access challenge')
    canonical=soup.select_one('link[rel="canonical"]')
    if canonical and source_identity(canonical.get('href',''))!=item['source_product_id']:raise ValueError('Canonical product identity mismatch')
    detail=parse_detail_page(body,listing_payload={'title_raw':item['title_raw'],'price':item['listing_price']})
    specs={}
    for row in scope.select('table.article-specs tr'):
        cells=row.find_all(['th','td'],recursive=False)
        if len(cells)>=2:specs[clean(cells[0].get_text()).casefold().rstrip(':')]=clean(cells[1].get_text(' ',strip=True))
    barcode_fields=[v for k,v in specs.items() if re.fullmatch(r'ean|barcode|upc|gtin(?:8|12|13|14)?',k) and v]
    codes=sorted({normalize_ean(v) for v in barcode_fields if normalize_ean(v)})
    if barcode_fields and (len(codes)!=1 or any(not normalize_ean(v) for v in barcode_fields)):raise ValueError('Invalid or ambiguous source identifier')
    price=detail.get('detail_price_seen')
    if price is None or Decimal(price)!=Decimal(item['listing_price']):raise ValueError('Listing/detail article price mismatch or unproven')
    if detail.get('availability')!='in_stock':raise ValueError('Current detail does not prove in-stock availability')
    name=detail.get('title_raw') or ''
    if not re.search(r'\b(?:\d?LP|VINYL)\b',detail.get('format') or '',re.I):raise ValueError('Vinyl format not proven')
    if re.search(r'\b(?:used|pre[- ]owned|second[- ]hand|tweedehands|occasion|CD|DVD|bundle|box)\b',name,re.I):raise ValueError('Used/non-vinyl/bundle title requires review')
    state=next((v for k,v in specs.items() if k in ('state','condition','staat','conditie')),None)
    if state and state.casefold() not in ('nieuw','new','sealed'):raise ValueError('Condition attribute requires review: '+state)
    return {**item,'status':'validated','observed_at':observed_at,'source_sha256':hashlib.sha256(body.encode()).hexdigest(),
      'source_title':name,'source_artist':next((specs[k] for k in ('artiest','artist','uitvoerende') if specs.get(k)),None),
      'source_album':next((specs[k] for k in ('album','titel','title') if specs.get(k)),None),'source_specs':specs,
      'price':item['listing_price'],'price_source':'listing','detail_price_crosscheck':price,'availability':'in_stock',
      'format_status':'vinyl','condition_status':'new','condition_basis':'explicit_attribute' if state else 'no_used_signal_policy',
      'gtin14':codes[0] if codes else None,'route':'EAN' if codes else 'ARTIST_TITLE',
      'ean_status':'EAN_AVAILABLE' if codes else 'EAN_NOT_FOUND','production_write':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,default=ROOT/'config/northend-album-pilot.json');args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text());items=manifest['records']
    if not 1<=len(items)<=25 or manifest.get('write') is not False:raise SystemExit('Only a read-only pilot of at most 25 records is allowed')
    for row in items:
        if source_identity(row['source_url'])!=row['source_product_id']:raise SystemExit('Invalid manifest identity')
    out=ROOT/'output/northend-album-pilot/result.json';out.parent.mkdir(parents=True,exist_ok=True)
    result={'schema_version':1,'manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
      'started_at':datetime.now(timezone.utc).isoformat(),'production_write':False,'records':[],'requests':[]}
    def save():out.write_text(json.dumps(result,indent=2)+'\n')
    session=requests.Session();session.headers.update({'User-Agent':UA,'Accept-Language':'nl-NL,nl;q=0.9'})
    last=None;delay=30.0
    def get(url):
        nonlocal last
        if last is not None:time.sleep(max(0,delay-(time.monotonic()-last)))
        last=time.monotonic()
        with session.get(url,timeout=30,stream=True,allow_redirects=False) as response:
            status=response.status_code
            if status!=200:raise RuntimeError('HTTP_'+str(status))
            raw=response.raw.read(2000001,decode_content=True)
            if len(raw)>2000000:raise RuntimeError('Response exceeds pilot size limit')
            body=raw.decode(response.encoding or 'utf-8',errors='replace')
            if re.search(r'cf-chl-|challenge-platform|<title>Just a moment',body,re.I):raise RuntimeError('ACCESS_CHALLENGE')
            result['requests'].append({'url':url,'status':status,'sha256':hashlib.sha256(body.encode()).hexdigest()});save()
            return body
    try:
        robots_url='https://www.northendhaarlem.nl/robots.txt';robots=RobotFileParser(robots_url)
        robots.parse(get(robots_url).splitlines());delay=max(delay,robots.crawl_delay(UA) or robots.crawl_delay('*') or 0)
        result['request_interval_seconds']=delay
        for i,item in enumerate(items):
            try:
                stamp=datetime.fromisoformat(item['listing_observed_at'])
                if not 0<=(datetime.now(timezone.utc)-stamp).total_seconds()<48*3600:raise ValueError('Listing evidence expired')
                if not robots.can_fetch(UA,item['source_url']):raise ValueError('robots_disallow')
                body=get(item['source_url']);record=parse_source(body,item,datetime.now(timezone.utc).isoformat())
            except Exception as error:
                record={**item,'status':'blocked','reason':str(error)}
                if str(error) in ('HTTP_401','HTTP_403','HTTP_429','ACCESS_CHALLENGE'):
                    result['records'].append(record)
                    result['records'] += [{**pending,'status':'deferred','reason':'shop_access_stopped'} for pending in items[i+1:]]
                    save();break
            result['records'].append(record);save()
            print(json.dumps({k:record.get(k) for k in ('source_product_id','status','route','reason')}),flush=True)
    except Exception as error:result['fatal_error']=str(error);save()
    finally:session.close()
    result['finished_at']=datetime.now(timezone.utc).isoformat();result['summary']={
      'selected':len(items),'processed':len(result['records']),'validated':sum(r['status']=='validated' for r in result['records']),
      'non_ean':sum(r.get('route')=='ARTIST_TITLE' for r in result['records']),
      'ean':sum(r.get('route')=='EAN' for r in result['records'])};save()
    print(json.dumps(result['summary']),flush=True)
    if result.get('fatal_error') or result['summary']['validated']==0:raise SystemExit(1)

if __name__=='__main__':main()
