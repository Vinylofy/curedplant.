"""Apply user-provided Velvet Delft NL and BE shipping rates only."""
from __future__ import annotations

import os
import psycopg


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("select id from public.shops where lower(domain)=%s", ("velvetdelft.nl",))
        shops = cur.fetchall()
        if len(shops) != 1:
            raise RuntimeError("Expected exactly one Velvet Delft shop")
        shop_id = shops[0][0]
        for country, cents in (("NL", 600), ("BE", 1200)):
            cur.execute("""select shop_slug,shop_id from public.shop_shipping_rules
                           where country_code=%s and (shop_id=%s or shop_slug=%s)""",
                        (country, shop_id, "velvetdelft"))
            rows = cur.fetchall()
            if len(rows) > 1 or (rows and rows[0] != ("velvetdelft", shop_id)):
                raise RuntimeError(f"Conflicting shipping rule for Velvet Delft/{country}")
            note = f"Verzending naar {country}: €{cents / 100:.2f}; tarief opgegeven door beheerder op 25 november 2026."
            cur.execute("""insert into public.shop_shipping_rules
                (shop_id,shop_slug,shop_name,country_code,currency,shipping_cost_cents,
                 free_shipping_threshold_cents,shipping_logic,shipping_note,confidence,
                 source_url,verified_at,active)
                values (%s,'velvetdelft','Velvet Music Delft',%s,'EUR',%s,null,'flat',%s,'verified',null,'2026-11-25',true)
                on conflict (shop_slug,country_code) do update set
                 shop_id=excluded.shop_id,shop_name=excluded.shop_name,currency=excluded.currency,
                 shipping_cost_cents=excluded.shipping_cost_cents,free_shipping_threshold_cents=null,
                 shipping_logic=excluded.shipping_logic,shipping_note=excluded.shipping_note,
                 confidence=excluded.confidence,source_url=null,verified_at=excluded.verified_at,
                 active=true,rules_version=public.shop_shipping_rules.rules_version+1,updated_at=now()
                """, (shop_id, country, cents, note))
            cur.execute("""select shipping_cost_cents,free_shipping_threshold_cents,active
                           from public.shop_shipping_rules where shop_id=%s and country_code=%s""", (shop_id, country))
            if cur.fetchall() != [(cents, None, True)]:
                raise RuntimeError(f"Shipping postcondition failed for Velvet Delft/{country}")
        print("Verified two user-provided Velvet Delft rates; committing transaction.")


if __name__ == "__main__":
    main()
