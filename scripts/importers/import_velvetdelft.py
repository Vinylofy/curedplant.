"""Strict EAN-only importer. CLI intentionally permits dry-run only until release approval."""
from datetime import datetime,timezone
from decimal import Decimal
import sys
from scripts.importers.common import CanonicalRecord,ImportConfig,strict_normalize_gtin
from scripts.importers.contracts import ShopImporterDefinition,ImportFileLayout
from scripts.importers.runner import run_registered_importer
from scripts.scrapers.velvetdelft import VINYL,safe_url,RELEASE
from urllib.parse import urlsplit

CONFIG=ImportConfig(shop_name='Velvet Music Delft',shop_domain='velvetdelft.nl',shop_country='NL',currency='EUR')


def map_velvet_row(row,line):
    try:
        gtin=strict_normalize_gtin(row.get('ean'))
        if not gtin or row.get('ean_status')!='verified' or row.get('gtin14')!=gtin:return None,'unverified_or_conflicting_gtin'
        if row.get('condition')!='new' or not VINYL.fullmatch(row.get('format','')):return None,'not_new_unambiguous_vinyl'
        if row.get('reason'):return None,'source_quarantine'
        url=safe_url(row['source_url'],True)
        if RELEASE.match(urlsplit(url).path)[1]!=str(row['source_product_id']):return None,'release_id_conflict'
        if not row.get('artist') or not row.get('title'):return None,'missing_artist_title'
        if row.get('currency')!='EUR':return None,'currency_conflict'
        price=Decimal(str(row['price']))
        if not price.is_finite() or price<=0:return None,'invalid_listing_price'
        at=datetime.fromisoformat(row['listing_observed_at']);detail=datetime.fromisoformat(row['detail_observed_at'])
        if any(t.tzinfo is None for t in (at,detail)):return None,'timezone_required'
        if not 0<=(datetime.now(timezone.utc)-at).total_seconds()<=48*3600:return None,'stale_listing'
        if not 0<=(datetime.now(timezone.utc)-detail).total_seconds()<=100*86400:return None,'stale_detail'
        avail=row['availability']
        if avail not in ('in_stock','supplier_order','preorder','out_of_stock','unknown'):return None,'invalid_availability'
        # Shared public price schema lacks supplier_order; never turn this into stock.
        public_availability='unknown' if avail=='supplier_order' else avail
        return CanonicalRecord(source_row_number=line,shop_name=CONFIG.shop_name,shop_domain=CONFIG.shop_domain,shop_country='NL',ean=str(row['ean']),gtin_normalized=gtin,artist=row['artist'],title=row['title'],format_label=row['format'],cover_url=None,product_url=url,price=float(price),currency='EUR',availability=public_availability,captured_at=at,product_handle=row['source_product_id'],detail_status='ok',is_secondhand=False,raw=row),None
    except (ValueError,KeyError,TypeError,ArithmeticError):return None,'invalid_source_fields'


SHOP_DEFINITION=ShopImporterDefinition(key='velvetdelft',config=CONFIG,importer_module='scripts.importers.import_velvetdelft',scraper_command_env='VINYLOFY_SCRAPER_CMD_VELVETDELFT',storage_prefix='velvetdelft',files=ImportFileLayout('output/velvetdelft/products.csv','output/velvetdelft/rejects.csv','output/velvetdelft/import-summary.json'),row_mapper=map_velvet_row,description=__doc__,required_columns=('source_product_id','source_url','artist','title','format','price','currency','availability','listing_observed_at','condition','ean','gtin14','ean_status','detail_observed_at','reason'),optional_columns=('regular_price','availability_raw','listing_url','detail_next_at'),tags=('vinyl','listing-first','ean-gated','manual-only'),include_in_all=False)

if __name__=='__main__':
    if '--dry-run' not in sys.argv:raise SystemExit('Velvet Delft publication is not approved. Use --dry-run.')
    run_registered_importer(SHOP_DEFINITION)
