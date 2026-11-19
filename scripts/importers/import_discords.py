#!/usr/bin/env python3
from __future__ import annotations

from scripts.importers.common import (CanonicalRecord, ImportConfig, infer_artist_title,
    normalize_text, parse_price, parse_timestamp, strict_normalize_gtin)
from scripts.importers.contracts import ImportFileLayout, ShopImporterDefinition
from scripts.importers.runner import run_registered_importer

CONFIG = ImportConfig(shop_name="Discords", shop_domain="discords.nl", shop_country="NL", currency="EUR")


def map_discords_row(row: dict, line_number: int):
    ean = strict_normalize_gtin(row.get("ean"))
    price = parse_price(row.get("price"))
    url = normalize_text(row.get("product_url"))
    artist, title = infer_artist_title(row.get("artist"), row.get("title"))
    if not ean: return None, "missing_or_invalid_ean"
    if not url: return None, "missing_url"
    if price is None: return None, "invalid_price"
    if not artist: return None, "missing_artist_after_inference"
    if not title: return None, "missing_title"
    availability = normalize_text(row.get("availability")).lower()
    if availability not in {"in_stock", "out_of_stock", "preorder", "unknown"}:
        availability = "unknown"
    return CanonicalRecord(source_row_number=line_number, shop_name=CONFIG.shop_name,
        shop_domain=CONFIG.shop_domain, shop_country=CONFIG.shop_country, ean=ean,
        artist=artist, title=title, format_label=normalize_text(row.get("format")) or "LP",
        cover_url=None, product_url=url, price=price, currency="EUR", availability=availability,
        captured_at=parse_timestamp(row.get("scraped_at")),
        product_handle=normalize_text(row.get("handle")) or None, detail_status="ok",
        is_secondhand=False, raw=row, cover_candidate_url=normalize_text(row.get("image_url")) or None,
        cover_candidate_source_type="shop_detail_image" if normalize_text(row.get("image_url")) else None,
        cover_candidate_page_url=url if normalize_text(row.get("image_url")) else None), None


SHOP_DEFINITION = ShopImporterDefinition(key="discords", config=CONFIG,
    importer_module="scripts.importers.import_discords",
    scraper_command_env="VINYLOFY_SCRAPER_CMD_DISCORDS", storage_prefix="discords",
    files=ImportFileLayout(csv_output_path="data/raw/discords/discords_products.csv",
        rejects_path="output/discords_rejects.csv", summary_path="output/discords_import_summary.json"),
    row_mapper=map_discords_row, description="Import Discords new-LP Shopify records",
    required_columns=("product_url", "ean", "artist", "title", "price", "scraped_at"),
    optional_columns=("product_id", "handle", "variant_id", "format", "compare_at_price",
        "currency", "availability", "image_url"), tags=("vinyl", "shopify", "new-lp"))


def main():
    run_registered_importer(SHOP_DEFINITION)


if __name__ == "__main__":
    main()
