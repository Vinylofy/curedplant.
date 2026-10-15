from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.importers.common import CanonicalRecord, ImportConfig, infer_artist_title, normalize_ean, normalize_text, parse_price, parse_timestamp, strict_normalize_gtin  # noqa: E402
from scripts.importers.contracts import ImportFileLayout, ShopImporterDefinition  # noqa: E402
from scripts.importers.runner import run_registered_importer  # noqa: E402

CONFIG = ImportConfig(shop_name="Best Kept Records", shop_domain="bestkeptrecords.nl", shop_country="NL", currency="EUR")


def map_bestkeptrecords_row(row: dict, line_number: int) -> tuple[CanonicalRecord | None, str | None]:
    ean = normalize_ean(row.get("ean")); gtin = strict_normalize_gtin(row.get("ean"))
    artist, title = infer_artist_title(row.get("artist"), row.get("title"))
    if not ean or not gtin: return None, "missing_or_invalid_ean"
    if not normalize_text(row.get("product_url")): return None, "missing_url"
    price = parse_price(row.get("price"))
    if price is None or price <= 0: return None, "invalid_price"
    if not artist or not title: return None, "missing_artist_or_title"
    if normalize_text(row.get("detail_status")).casefold() != "ok": return None, "detail_not_verified"
    return CanonicalRecord(
        source_row_number=line_number, shop_name=CONFIG.shop_name, shop_domain=CONFIG.shop_domain,
        shop_country=CONFIG.shop_country, ean=ean, artist=artist, title=title,
        format_label=normalize_text(row.get("format")) or "Vinyl", cover_url=None,
        product_url=normalize_text(row.get("product_url")), price=price, currency=CONFIG.currency,
        availability=normalize_text(row.get("availability")) if normalize_text(row.get("availability")) in {"in_stock", "out_of_stock", "preorder"} else "unknown",
        captured_at=parse_timestamp(row.get("scraped_at")), product_handle=normalize_text(row.get("product_key")),
        detail_status="ok", is_secondhand=normalize_text(row.get("is_secondhand")).casefold() == "true",
        raw=row, gtin_normalized=gtin,
    ), None


SHOP_DEFINITION = ShopImporterDefinition(
    key="bestkeptrecords", config=CONFIG, importer_module="scripts.importers.import_bestkeptrecords",
    scraper_command_env="VINYLOFY_SCRAPER_CMD_BESTKEPTRECORDS", storage_prefix="bestkeptrecords",
    files=ImportFileLayout(csv_output_path="data/raw/bestkeptrecords/bestkeptrecords_products.csv", rejects_path="output/bestkeptrecords_rejects.csv", summary_path="output/bestkeptrecords_import_summary.json"),
    row_mapper=map_bestkeptrecords_row, description="Import Best Kept Records listing-first EAN-gated catalog",
    required_columns=("scraped_at", "product_url", "ean", "artist", "title", "price", "availability", "detail_status"),
    optional_columns=("source_shop", "product_key", "standard_price", "currency", "format", "image_url", "page_found", "is_secondhand", "release_date", "label", "genre", "detail_error", "enriched_at"),
    tags=("vinyl", "woocommerce", "listing-first", "barcode-gated", "large-catalog"), include_in_all=False,
)


def main() -> None:
    run_registered_importer(SHOP_DEFINITION)


if __name__ == "__main__":
    main()
