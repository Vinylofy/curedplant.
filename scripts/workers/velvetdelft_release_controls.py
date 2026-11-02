"""Velvet-only public-market registration and canonical-format conflict holds."""
from datetime import datetime,timezone
import os
import re
import psycopg
from psycopg.types.json import Jsonb
from scripts.importers.common import strict_normalize_gtin,identifier_variants
from scripts.importers.import_velvetdelft import CONFIG

NON_VINYL=re.compile(r'(?<![a-z])(cd|sacd|dvd|cassette|blu[ -]?ray)(?![a-z])',re.I)
DELIVERY_URL='https://www.velvetdelft.nl/nl/pagina/leveringsvoorwaarden'
DELIVERY_QUOTE='Bestellingen worden met tracking verstuurd via PostNL.'
DELIVERY_OBSERVED='2026-11-02T14:37:39.669401+00:00'


def conflicts(rows,dsn):
    codes={strict_normalize_gtin(r.get('ean')) for r in rows if r.get('ean_status')=='verified'}-{None}
    variants=sorted({v for code in codes for v in identifier_variants(code)})
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        found=conn.execute('select id,gtin_normalized,ean,format_label from products where gtin_normalized=any(%s::text[]) or ean=any(%s::text[])',(variants,variants)).fetchall()
    return {(strict_normalize_gtin(r[1]) or strict_normalize_gtin(r[2])):{'product_id':str(r[0]),'format':r[3]} for r in found if NON_VINYL.search(r[3] or '')}


def hold(rows,blocked,dsn):
    held=[]
    if not blocked:return held
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        for row in rows:
            code=strict_normalize_gtin(row.get('ean'));evidence=blocked.get(code)
            if not evidence:continue
            conn.execute("update prices p set is_active=false,updated_at=now() from shops s where p.shop_id=s.id and s.domain=%s and p.product_id=%s",(CONFIG.shop_domain,evidence['product_id']))
            conn.execute("update staged_offers set stage_status='quarantined',stage_reason='canonical_format_conflict' where shop_id='velvetdelft' and source_product_id=%s",(row['source_product_id'],))
            conn.execute("""insert into quarantine_offers(shop_id,source_url,ean_normalized,ean_match_key,issue_type,issue_detail,payload)
                select 'velvetdelft',%s,%s,%s,'canonical_format_conflict',%s,%s
                where not exists(select 1 from quarantine_offers where shop_id='velvetdelft' and source_url=%s and issue_type='canonical_format_conflict' and resolved_at is null)""",(row['source_url'],row.get('ean'),code,'Listing vinyl conflicts with existing product format '+evidence['format'],Jsonb({'source_product_id':row['source_product_id'],'canonical':evidence,'source_format':row['format']}),row['source_url']))
            held.append(row['source_product_id'])
    return held


def register_nl(dsn):
    # Reviewed source combination: Dutch shop/address and explicit PostNL delivery.
    # Confirm NL only; shipping prices, thresholds and other markets stay unknown.
    with psycopg.connect(dsn,prepare_threshold=None) as conn:
        shops=conn.execute('select id from shops where domain=%s',(CONFIG.shop_domain,)).fetchall()
        if len(shops)!=1:raise ValueError('Expected exactly one registered Velvet Delft shop')
        shop=shops[0][0]
        previous=conn.execute("select status from shop_shipping_destinations where shop_id=%s and country_code='NL'",(shop,)).fetchone()
        if previous and previous[0] not in ('unknown','confirmed'):raise ValueError('Explicit NL market exclusion must be reviewed')
        conn.execute("""insert into shop_shipping_destinations(shop_id,country_code,status,source_url,verified_at,note)
            values(%s,'NL','confirmed',%s,%s,%s) on conflict(shop_id,country_code) do update set
            status='confirmed',source_url=excluded.source_url,verified_at=excluded.verified_at,note=excluded.note
            where shop_shipping_destinations.status='unknown'""",(shop,DELIVERY_URL,DELIVERY_OBSERVED,'Source reviewed: '+DELIVERY_QUOTE+' Shop: Voldersgracht 3, 2611 ET Delft, Netherlands. Shipping fees not inferred.'))
    return {'shop_id':str(shop),'country':'NL','status':'confirmed','source_url':DELIVERY_URL,'quote':DELIVERY_QUOTE,'fees':'unknown'}


def apply(rows,dsn):
    blocked=conflicts(rows,dsn)
    held=hold(rows,blocked,dsn)
    return {'canonical_conflicts':blocked,'held_release_ids':held,'market':register_nl(dsn)}
