"""Apply eight explicitly verified shop/market shipping rates transactionally."""
from __future__ import annotations

import os
import psycopg

ROWS = [
    ("discords.nl", "discords", "Discords", "NL", 695, 7000, "threshold", "Regulier pakket: €6,95; gratis verzending vanaf €70.", "https://discords.nl/policies/shipping-policy"),
    ("discords.nl", "discords", "Discords", "BE", 995, None, "flat", "Regulier pakket naar België: €9,95 per pakket.", "https://discords.nl/policies/shipping-policy"),
    ("bestkeptrecords.nl", "bestkeptrecords", "Best Kept Records", "NL", 850, None, "flat", "Verzending naar Nederland: €8,50.", "https://bestkeptrecords.nl/algemene-voorwaarden/"),
    ("bestkeptrecords.nl", "bestkeptrecords", "Best Kept Records", "BE", 1100, None, "flat", "Verzending naar België: €11,00.", "https://bestkeptrecords.nl/algemene-voorwaarden/"),
    ("rockinoutrecords.nl", "rockinoutrecords", "Rockin' Out Records", "NL", 799, None, "flat", "LP-pakket via DHL: €7,99; PostNL €8,49. Keuze bij bestellen.", "https://rockinoutrecords.nl/algemene-voorwaarden/"),
    ("rockinoutrecords.nl", "rockinoutrecords", "Rockin' Out Records", "BE", 1249, None, "flat", "Pakket via DHL: €12,49; PostNL €12,99. Keuze bij bestellen.", "https://rockinoutrecords.nl/algemene-voorwaarden/"),
    ("jpc.de", "jpc", "jpc", "NL", 399, None, "flat", "Nederland: €3,99 per bestelling volgens verzendtabel.", "https://www.jpc.de/jpcng/home/static/-/page/porto.html"),
    ("jpc.de", "jpc", "jpc", "BE", 299, None, "flat", "België: €2,99 per bestelling volgens verzendtabel.", "https://www.jpc.de/jpcng/home/static/-/page/porto.html"),
]


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for domain, slug, name, country, cost, threshold, logic, note, source in ROWS:
            cur.execute("select id from public.shops where lower(domain)=%s", (domain,))
            shops = cur.fetchall()
            if len(shops) != 1:
                raise RuntimeError(f"Expected exactly one shop for {domain}, found {len(shops)}")
            shop_id = shops[0][0]
            cur.execute("select shop_id from public.shop_shipping_rules where shop_slug=%s and country_code=%s", (slug, country))
            existing = cur.fetchall()
            if len(existing) > 1 or (existing and existing[0][0] != shop_id):
                raise RuntimeError(f"Shipping rule identity conflict for {slug}/{country}")
            cur.execute("""insert into public.shop_shipping_rules
                (shop_id, shop_slug, shop_name, country_code, currency, shipping_cost_cents,
                 free_shipping_threshold_cents, shipping_logic, shipping_note, confidence,
                 source_url, verified_at, active)
                values (%s,%s,%s,%s,'EUR',%s,%s,%s,%s,'verified',%s,'2026-11-25',true)
                on conflict (shop_slug,country_code) do update set
                 shop_id=excluded.shop_id,shop_name=excluded.shop_name,currency=excluded.currency,
                 shipping_cost_cents=excluded.shipping_cost_cents,
                 free_shipping_threshold_cents=excluded.free_shipping_threshold_cents,
                 shipping_logic=excluded.shipping_logic,shipping_note=excluded.shipping_note,
                 confidence=excluded.confidence,source_url=excluded.source_url,
                 verified_at=excluded.verified_at,active=true,
                 rules_version=public.shop_shipping_rules.rules_version+1,updated_at=now()
                """, (shop_id, slug, name, country, cost, threshold, logic, note, source))
            cur.execute("""select shipping_cost_cents,free_shipping_threshold_cents,confidence,active
                           from public.shop_shipping_rules where shop_id=%s and shop_slug=%s and country_code=%s""",
                        (shop_id, slug, country))
            if cur.fetchall() != [(cost, threshold, "verified", True)]:
                raise RuntimeError(f"Shipping postcondition failed for {slug}/{country}")
        print(f"Verified {len(ROWS)} shipping rates; committing transaction.")


if __name__ == "__main__":
    main()
