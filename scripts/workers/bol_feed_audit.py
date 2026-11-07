"""Read-only acceptance audit of an existing, complete FTPS review.

Reuses the FTPS selector output and existing Marketing API validation; never
creates products, changes formats, publishes prices or deactivates offers.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import re
import urllib.request
import urllib.parse
import psycopg
from psycopg.rows import dict_row
from scripts.importers.bol_feed import FeedError
from scripts.importers.bol_api_prices import Client, SHOP_ID, api_ean, verified_ean, normalize_offer
from scripts.importers.bol_api_review import ReviewError, CATALOG_URL, request_json, schema_paths
from scripts.importers.common import strict_normalize_gtin


def classify_existing(product, selected, now):
    gtin = strict_normalize_gtin(str(product.get('ean') or ''))
    registered = product.get('gtin_normalized')
    present = gtin in selected or registered in selected
    last_seen = product.get('last_seen_at')
    visible = bool(last_seen and now - timedelta(hours=48) <= last_seen <= now + timedelta(minutes=5)
                   and product.get('availability') in {'in_stock', 'unknown'}
                   and product.get('currency') == 'EUR' and product.get('price', 0) > 0)
    reason, consumer_ean = None, None
    try:
        _, checked = verified_ean(product)
        consumer_ean = api_ean(checked)
    except FeedError as exc:
        reason = str(exc)
    return {'present': present, 'frontend_visible': visible,
            'api_eligible': reason is None, 'reason': reason, 'consumer_ean': consumer_ean}


def catalogue_facts(client, ean):
    url = CATALOG_URL + ean + '?' + urllib.parse.urlencode({'country-code':'NL','include-offer':'false'})
    request = urllib.request.Request(url,headers={'Authorization':'Bearer '+client.token,
                                                 'Accept':'application/json','Accept-Language':'nl'})
    data = request_json(request,'catalogue_identity')
    facts = []
    def visit(value,path=''):
        if len(facts)>=30:
            return
        if isinstance(value,dict):
            labels = [str(value.get(k,'')) for k in ('name','key','label','type')]
            if any(re.search(r'format|drager|carrier|binding|categor|productgroup',v,re.I) for v in labels):
                clean = {k:v for k,v in value.items() if k in {'name','key','label','type','value','values','id','categoryId'}
                         and len(json.dumps(v))<1000}
                facts.append({'path':path,'value':clean})
            for key,item in value.items():
                if re.search(r'category|categorie|productgroup',key,re.I) and len(json.dumps(item))<1000:
                    facts.append({'path':path+'.'+key,'value':item})
                if key not in {'description','images','imageUrl','media','title','artist'}:
                    visit(item,path+'.'+key)
        elif isinstance(value,list):
            for i,item in enumerate(value[:100]):visit(item,path+f'[{i}]')
    visit(data)
    return {'schema':schema_paths(data),'format_category_facts':facts}


def audit_catalogue(plan, dsn, *, api_sample=0, site_id='', client=None, now=None, inspect_catalogue=False):
    if (not plan.get('complete_feed') or plan.get('source') != 'bol_affiliate_productfeed'
            or plan.get('errors') or not 0 <= api_sample <= 50):
        raise FeedError('complete_successful_review_required')
    now = now or datetime.now(timezone.utc)
    selected = {o['gtin'] for o in plan['offers'] if o['country'] == 'NL'}
    counts, missing_reasons = Counter(), Counter()
    missing, conflicts = [], []
    conflict_gtins = {r['gtin'] for r in plan.get('match_conflicts', []) + plan.get('quarantined_identity_conflicts', [])}
    with psycopg.connect(dsn, prepare_threshold=None, row_factory=dict_row) as conn:
        conn.execute('set transaction isolation level repeatable read read only')
        with conn.cursor() as cur:
            cur.execute('''select p.id,p.ean,p.gtin_normalized,p.format_label,
                         p.metadata_source,p.metadata_status,p.metadata_needs_review,
                         pr.price,pr.currency,pr.availability,pr.last_seen_at
                         from public.prices pr join public.products p on p.id=pr.product_id
                         where pr.shop_id=%s and pr.is_active=true order by p.id''', (SHOP_ID,))
            active = cur.fetchall()
            cur.execute('''select id,ean,gtin_normalized,format_label,metadata_source,
                         metadata_status,metadata_needs_review from public.products
                         where gtin_normalized=any(%s) order by gtin_normalized''', (sorted(conflict_gtins),))
            conflict_rows = cur.fetchall()
    source_rejections = {}
    for row in plan.get('coverage_source_rejections', []):
        source_rejections.setdefault(row['gtin'], []).append(row)
    source_absent = set(plan.get('coverage_source_absent_gtins', []))
    source_reasons = Counter()
    for product in active:
        state = classify_existing(product, selected, now)
        counts['active_shop_offers'] += 1
        counts['covered' if state['present'] else 'missing'] += 1
        if state['frontend_visible']:
            counts['frontend_visible'] += 1
        if state['api_eligible']:
            counts['api_eligible'] += 1
        if not state['present']:
            reason = state['reason'] or 'api_eligible_not_in_selected_feed'
            missing_reasons[reason] += 1
            if state['frontend_visible']:
                counts['missing_frontend_visible'] += 1
            if state['api_eligible']:
                counts['missing_api_eligible'] += 1
                if state['frontend_visible']:
                    counts['missing_api_eligible_frontend_visible'] += 1
            source_evidence = source_rejections.get(gtin := strict_normalize_gtin(str(product.get('ean') or '')), [])
            source_reason = (';'.join(sorted({r['reason'] for r in source_evidence})) if source_evidence else
                             'absent_from_entertainment_feed' if gtin in source_absent else 'not_explained_by_source_snapshot')
            source_reasons[source_reason] += 1
            missing.append({'source_reason':source_reason,'source_evidence':source_evidence,'product_id':str(product['id']), 'ean':product['ean'],
                            'gtin':product['gtin_normalized'], 'format':product['format_label'],
                            'last_seen_at':product['last_seen_at'].isoformat() if product['last_seen_at'] else None,
                            'availability':product['availability'], 'price':str(product['price']),
                            'metadata_source':product['metadata_source'], 'reason':reason,
                            'frontend_visible':state['frontend_visible'],
                            'api_eligible':state['api_eligible'], 'consumer_ean':state['consumer_ean']})
    for row in conflict_rows:
        conflicts.append({k:(str(v) if k=='id' else v) for k,v in row.items()})
    samples = sorted((r for r in missing if r['api_eligible']),
                     key=lambda r:(not r['frontend_visible'],r['product_id']))[:api_sample]
    api_results = []
    client = client or (Client() if samples else None)
    previous_call = None
    for sample in samples:
        if previous_call is not None:
            time.sleep(max(0, 1 - (time.monotonic() - previous_call)))
        previous_call = time.monotonic()
        result = {'product_id':sample['product_id'], 'ean':sample['ean'],
                  'frontend_visible':sample['frontend_visible']}
        try:
            offer = client.best_offer(sample['consumer_ean'])
            if offer is None:
                result['status'] = 'no_current_api_offer'
            else:
                product = {'ean':sample['ean'], 'gtin_normalized':sample['gtin'],
                           'format_label':sample['format']}
                normalized = normalize_offer(product, offer, site_id, now)
                result.update(status='valid_current_api_offer',price=normalized['price'],
                              availability=normalized['availability'],source_product_id=normalized['product_id'])
        except FeedError as exc:
            result.update(status='api_offer_rejected',reason=str(exc))
        except ReviewError as exc:
            result.update(status='api_check_error',stage=exc.stage,reason=exc.reason,http_status=exc.status)
        if inspect_catalogue and result.get('status') == 'valid_current_api_offer':
            time.sleep(max(0,1-(time.monotonic()-previous_call)))
            previous_call=time.monotonic()
            try:
                result['catalogue_facts']=catalogue_facts(client,sample['consumer_ean'])
            except ReviewError as exc:
                result['catalogue_error']={'stage':exc.stage,'reason':exc.reason,'http_status':exc.status}
        api_results.append(result)
    return {'status':'catalogue_audited','database_writes':0,'errors':[],
            'source_at':plan['captured_at'],'feed_sha256':plan['feed_sha256'],
            'audited_at':now.isoformat(),'counts':dict(counts),
            'missing_reasons':dict(missing_reasons),'source_reasons':dict(source_reasons),'missing_offers':missing,
            'format_conflicts':conflicts,'api_sample':api_results,
            'api_sample_counts':dict(Counter(r['status'] for r in api_results))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--catalog-facts',action='store_true')
    parser.add_argument('--api-sample',type=int,default=0)
    parser.add_argument('--output',type=Path,default=Path('output/bol/catalogue-audit.json'))
    args=parser.parse_args()
    try:
        result=audit_catalogue(json.loads(args.review.read_text(encoding='utf-8')),
                               os.environ['DATABASE_URL'],api_sample=args.api_sample,
                               site_id=os.environ.get('BOL_SITE_ID',''),inspect_catalogue=args.catalog_facts)
    except Exception as exc:
        result={'status':'blocked','database_writes':0,
                'errors':[str(exc) if isinstance(exc,FeedError) else type(exc).__name__]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'missing_offers','format_conflicts','api_sample'}}))
    return int(bool(result['errors']))

if __name__=='__main__':
    raise SystemExit(main())
