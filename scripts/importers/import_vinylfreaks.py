#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.importers.common import (
    CanonicalRecord, ImportConfig, normalize_text, parse_price, parse_timestamp,
    strict_normalize_gtin,
)
from scripts.importers.contracts import ImportFileLayout, ShopImporterDefinition
from scripts.importers.runner import run_registered_importer

CONFIG = ImportConfig(shop_name="Vinyl Freaks", shop_domain="vinyl-freaks.nl", shop_country="NL", currency="EUR")


def map_vinylfreaks_row(row: dict, line_number: int):
    ean = normalize_text(row.get("ean"))
    if not re.fullmatch(r"(?:\d{8}|\d{12}|\d{13}|\d{14})", ean, re.ASCII):
        return None, "missing_or_invalid_ean"
    gtin = strict_normalize_gtin(ean)
    if not gtin:
        return None, "missing_or_invalid_ean"
    if row.get("detail_status") != "ok":
        return None, "detail_not_verified"
    if row.get("ean_source") not in {"catalogue_number", "gtin", "gtin8", "gtin12", "gtin13", "gtin14"}:
        return None, "unverified_ean_source"
    if row.get("ean_source") == "catalogue_number" and normalize_text(row.get("catalogue_number")) != ean:
        return None, "catalogue_ean_mismatch"
    product_url = normalize_text(row.get("product_url"))
    parsed = urlsplit(product_url)
    if parsed.scheme != "https" or parsed.hostname != CONFIG.shop_domain or not parsed.path.startswith("/plaat/") or parsed.username or parsed.password:
        return None, "invalid_product_url"
    price = parse_price(row.get("price"))
    if price is None or not (0 < price < float("inf")):
        return None, "invalid_price"
    artist, title = normalize_text(row.get("artist")), normalize_text(row.get("title"))
    if not artist or not title:
        return None, "missing_artist_or_title"
    availability = normalize_text(row.get("availability"))
    if availability not in {"in_stock", "out_of_stock", "preorder", "unknown"}:
        availability = "unknown"
    cover = normalize_text(row.get("cover_candidate_url"))
    if cover and urlsplit(cover).scheme != "https":
        cover = ""
    return CanonicalRecord(
        source_row_number=line_number, shop_name=CONFIG.shop_name, shop_domain=CONFIG.shop_domain,
        shop_country=CONFIG.shop_country, ean=ean, artist=artist, title=title,
        format_label=normalize_text(row.get("format")) or "Vinyl", cover_url=None,
        product_url=product_url, price=price, currency="EUR", availability=availability,
        captured_at=parse_timestamp(row.get("scraped_at")),
        product_handle=normalize_text(row.get("product_key")) or None,
        detail_status="ok", is_secondhand=False, raw=row, gtin_normalized=gtin,
        cover_candidate_url=cover or None,
        cover_candidate_source_type="shop_detail_image" if cover else None,
        cover_candidate_page_url=product_url if cover else None,
    ), None


SHOP_DEFINITION = ShopImporterDefinition(
    key="vinylfreaks", config=CONFIG, importer_module="scripts.importers.import_vinylfreaks",
    scraper_command_env="VINYLOFY_SCRAPER_CMD_VINYLFREAKS", storage_prefix="vinylfreaks",
    files=ImportFileLayout(
        csv_output_path="data/raw/vinylfreaks/vinylfreaks_master.csv",
        rejects_path="output/vinylfreaks_rejects.csv",
        summary_path="output/vinylfreaks_import_summary.json",
    ), row_mapper=map_vinylfreaks_row,
    required_columns=("scraped_at", "product_url", "ean", "artist", "title", "price", "availability", "detail_status", "ean_source", "catalogue_number"),
    optional_columns=("source_shop", "product_id", "product_key", "format", "standard_price", "is_sale", "currency", "image_url", "page_found", "discogs_release_id", "label", "detail_error", "detail_availability_observed", "cover_candidate_url", "enriched_at"),
    description="Import Vinyl Freaks listing-first, strictly barcode-gated CSV",
    tags=("vinyl", "woocommerce", "listing-first", "barcode-gated"), include_in_all=False,
)


if __name__ == "__main__":
    run_registered_importer(SHOP_DEFINITION)
