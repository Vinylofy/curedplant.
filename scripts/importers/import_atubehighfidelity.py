"""EAN-only A Tube contract; non-EAN rows belong to the separate album route."""
from datetime import datetime,timezone
from decimal import Decimal
from urllib.parse import urlsplit
from scripts.importers.common import CanonicalRecord,ImportConfig,strict_normalize_gtin
from scripts.importers.contracts import ShopImporterDefinition,ImportFileLayout
from scripts.importers.runner import run_registered_importer

CONFIG=ImportConfig(shop_name='A Tube High Fidelity',shop_domain='atube-highfidelity.nl',shop_country='NL',currency='EUR')


def map_atube_row(row,line):
    try:
        code=strict_normalize_gtin(row.get('ean_raw'))
        if not code or row.get('route')!='EAN':return None,'no_verified_ean'
        if row.get('status')!='validated' or row.get('detail_status')!='ok':return None,'detail_not_verified'
        if row.get('format_status')!='vinyl' or row.get('condition_status')!='new':return None,'new_vinyl_unproven'
        if not row.get('artist_raw') or not row.get('album_raw'):return None,'artist_album_unproven'
        if row.get('currency')!='EUR':return None,'currency_conflict'
        url=row.get('offer_url') or row['source_url'];p=urlsplit(url)
        if p.scheme!='https' or (p.hostname or '').removeprefix('www.')!=CONFIG.shop_domain or not p.path.startswith('/product/') or p.username or p.password or p.fragment or p.port not in (None,443):return None,'invalid_product_url'
        price=Decimal(str(row['price']))
        if not price.is_finite() or price<=0 or price!=Decimal(str(row['detail_price_crosscheck'])):return None,'listing_price_unproven'
        observed=datetime.fromisoformat(row['listing_observed_at'])
        detail=datetime.fromisoformat(row['detail_observed_at'])
        if any(not 0<=(datetime.now(timezone.utc)-at).total_seconds()<=48*3600 for at in (observed,detail)):return None,'stale_evidence'
        if row.get('availability') not in ('in_stock','unknown','out_of_stock','preorder'):return None,'invalid_availability'
        return CanonicalRecord(source_row_number=line,shop_name=CONFIG.shop_name,shop_domain=CONFIG.shop_domain,shop_country='NL',
          ean=str(row['ean_raw']),gtin_normalized=code,artist=row['artist_raw'],title=row['album_raw'],format_label='Vinyl',cover_url=None,
          product_url=url,price=float(price),currency='EUR',availability=row['availability'],captured_at=observed,
          product_handle=str(row['source_product_id']),detail_status='ok',is_secondhand=False,raw=row),None
    except (ValueError,TypeError,KeyError,ArithmeticError):return None,'invalid_source_fields'


SHOP_DEFINITION=ShopImporterDefinition(key='atubehighfidelity',config=CONFIG,importer_module='scripts.importers.import_atubehighfidelity',
 scraper_command_env='VINYLOFY_SCRAPER_CMD_ATUBEHIGHFIDELITY',storage_prefix='atubehighfidelity',
 files=ImportFileLayout('output/atubehighfidelity/products.csv','output/atubehighfidelity/rejects.csv','output/atubehighfidelity/import-summary.json'),
 row_mapper=map_atube_row,required_columns=('ean_raw','route','status','detail_status','title_raw','artist_raw','album_raw','source_url','price','currency','listing_observed_at','detail_observed_at','detail_price_crosscheck','format_status','condition_status','availability'),
 optional_columns=('source_product_id','offer_url','gtin14'),tags=('vinyl','listing-first','barcode-gated'),include_in_all=False)

if __name__=='__main__':run_registered_importer(SHOP_DEFINITION)
