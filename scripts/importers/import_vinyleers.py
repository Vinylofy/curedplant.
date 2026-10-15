from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.importers.common import (  # noqa: E402
    CanonicalRecord, ImportConfig, infer_artist_title, normalize_ean, normalize_text,
    parse_price, parse_timestamp, strict_normalize_gtin,
)
from scripts.importers.contracts import ImportFileLayout, ShopImporterDefinition  # noqa: E402
from scripts.importers.runner import run_registered_importer  # noqa: E402


CONFIG = ImportConfig(shop_name="Vinyleers", shop_domain="vinyleers.com", shop_country="NL", currency="EUR")


def map_vinyleers_row(row: dict, line_number: int) -> tuple[CanonicalRecord | None, str | None]:
    ean = normalize_ean(row.get("ean"))
    gtin = strict_normalize_gtin(row.get("ean"))
    artist, title = infer_artist_title(row.get("artist"), row.get("title"))
    price = parse_price(row.get("price"))
    product_url = normalize_text(row.get("product_url"))
    if not ean or not gtin:
        return None, "missing_or_invalid_ean"
    if normalize_text(row.get("detail_status")).casefold() != "ok":
        return None, "detail_not_verified"
    if normalize_text(row.get("new_badge")).casefold() != "true":
        return None, "not_explicitly_new"
    if normalize_text(row.get("new_evidence")).casefold() != "true":
        return None, "missing_new_condition_evidence"
    if normalize_text(row.get("is_secondhand")).casefold() == "true":
        return None, "secondhand"
    if not product_url:
        return None, "missing_url"
    if price is None or price <= 0:
        return None, "invalid_price"
    if not artist or not title:
        return None, "missing_artist_or_title"
    availability = normalize_text(row.get("availability"))
    if availability not in {"in_stock", "out_of_stock", "preorder"}:
        availability = "unknown"
    image_url = normalize_text(row.get("image_url")) or None
    return CanonicalRecord(
        source_row_number=line_number, shop_name=CONFIG.shop_name, shop_domain=CONFIG.shop_domain,
        shop_country=CONFIG.shop_country, ean=ean, artist=artist, title=title,
        format_label=normalize_text(row.get("format")) or "Vinyl", cover_url=None,
        product_url=product_url, price=price, currency=CONFIG.currency, availability=availability,
        captured_at=parse_timestamp(row.get("scraped_at")), product_handle=normalize_text(row.get("product_key")) or None,
        detail_status="ok", is_secondhand=False, raw=row, gtin_normalized=gtin,
        cover_candidate_url=image_url, cover_candidate_source_type="shop_listing_image" if image_url else None,
        cover_candidate_page_url=product_url if image_url else None, cover_candidate_queue_priority=100 if image_url else None,
    ), None


SHOP_DEFINITION = ShopImporterDefinition(
    key="vinyleers", config=CONFIG, importer_module="scripts.importers.import_vinyleers",
    scraper_command_env="VINYLOFY_SCRAPER_CMD_VINYLEERS", storage_prefix="vinyleers",
    files=ImportFileLayout(csv_output_path="data/raw/vinyleers/vinyleers_products.csv", rejects_path="output/vinyleers_rejects.csv", summary_path="output/vinyleers_import_summary.json"),
    row_mapper=map_vinyleers_row,
    description="Import Vinyleers new-only, listing-first EAN-gated vinyl CSV",
    required_columns=("scraped_at", "product_url", "ean", "artist", "title", "price", "currency", "availability", "detail_status", "new_badge", "new_evidence"),
    optional_columns=("source_shop", "product_id", "variant_id", "product_key", "standard_price", "is_sale", "format", "image_url", "page_found", "is_secondhand", "detail_price", "price_match", "detail_error", "enriched_at"),
    tags=("vinyl", "shopify", "listing-first", "barcode-gated", "new-only"), include_in_all=False,
)


if __name__ == "__main__":
    run_registered_importer(SHOP_DEFINITION)
