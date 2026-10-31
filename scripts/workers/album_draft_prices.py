"""Refresh only existing North End pilot drafts from validated catalogue prices.
Never creates offers, changes album/EAN identity, or publishes a draft.
"""
from decimal import Decimal,InvalidOperation
import os
import re
from urllib.parse import urlsplit
import psycopg
from psycopg.types.json import Jsonb

PILOT='northend-25-20261031'


def candidates(records):
    found={};conflicts=set()
    for row in records:
        url=urlsplit(str(row.get('source_url','')))
        match=re.search(r'^/a-(\d+)(?:/|$)',url.path)
        if url.scheme!='https' or url.hostname not in ('northendhaarlem.nl','www.northendhaarlem.nl') or not match or row.get('currency')!='EUR':continue
        try:
            price=Decimal(str(row.get('price')))
            if not price.is_finite() or price<=0:continue
        except (InvalidOperation,ValueError):continue
        availability=row.get('availability')
        if availability not in ('in_stock','out_of_stock','preorder','unknown'):continue
        item={'source_product_id':match.group(1),'price':str(price),'availability':availability}
        key=match.group(1)
        if key in found and found[key]!=item:conflicts.add(key)
        found[key]=item
    return [v for k,v in found.items() if k not in conflicts]


def refresh_drafts(conn,records,observed_at):
    if conn.execute("select to_regclass('public.album_alternative_offers')").fetchone()[0] is None:
        return {'status':'schema_not_installed','updated':0}
    data=candidates(records)
    result=conn.execute("""with source as (
      select * from jsonb_to_recordset(%s::jsonb) as x(source_product_id text,price numeric,availability text)
    ) update public.album_alternative_offers o set price=s.price,
      availability=s.availability,last_seen_at=greatest(o.last_seen_at,%s::timestamptz),
      last_price_checked_at=%s::timestamptz,
      metadata=o.metadata||jsonb_build_object('listing_refresh_run',%s::text)
      from source s,public.shops shop
      where o.shop_id=shop.id and shop.domain='northendhaarlem.nl' and o.source_product_id=s.source_product_id
        and o.metadata->>'pilot_id'=%s and o.publication_status='draft' and o.promotion_status='none'
        and o.currency='EUR' and o.ean_status='EAN_NOT_FOUND'
        and (o.last_price_checked_at is null or o.last_price_checked_at<=%s::timestamptz)
      returning o.id""",(Jsonb(data),observed_at,observed_at,os.environ.get('GITHUB_RUN_ID','manual'),PILOT,observed_at))
    updated=len(result.fetchall())
    return {'status':'existing_drafts_refreshed','updated':updated,'publications':0}


def update_northend_drafts(records,observed_at):
    with psycopg.connect(os.environ['DATABASE_URL'],prepare_threshold=None) as conn:
        return refresh_drafts(conn,records,observed_at)
