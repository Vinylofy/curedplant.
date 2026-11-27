#!/usr/bin/env python3
"""Bounded audit and explicitly gated repair of technical product titles."""
from __future__ import annotations
import argparse, csv, json, os, re
from pathlib import Path

QOTSA_ID = "fc7a7dcc-d09c-4e67-b977-66359ab37ba8"
QOTSA_EAN = "0191401214230"
PATTERN = re.compile(r"^(?:(?:vinyl|lp|record)(?:\s+(?:ean|upc))?\s*)?\d{8,14}$|^unknown(?:\s+(?:album|title|artist))?$", re.I)

def technical(value):
    return not str(value or "").strip() or bool(PATTERN.fullmatch(" ".join(str(value).split())))

def main():
    import psycopg
    p=argparse.ArgumentParser(); p.add_argument("--output",default="output/metadata-quality.csv")
    p.add_argument("--limit",type=int,default=5000); p.add_argument("--repair-qotsa",action="store_true")
    a=p.parse_args(); dsn=os.environ.get("DATABASE_URL","").strip()
    if not dsn: raise SystemExit("DATABASE_URL is required")
    with psycopg.connect(dsn) as conn:
        conn.execute("begin")
        predicate="""p.title is null or btrim(p.title)='' or p.artist is null or btrim(p.artist)=''
             or p.title ~* '^(vinyl|lp|record)( (ean|upc))? [0-9]{8,14}$'
             or p.title ~ '^[0-9]{8,14}$' or p.title ~* '^unknown( (album|title|artist))?$'
             or p.artist ~* '^unknown artist$'"""
        totals=conn.execute(f"""select count(*)::int,
          count(*) filter(where exists(select 1 from prices pr where pr.product_id=p.id and pr.is_active
            and pr.last_seen_at>=now()-interval '48 hours'))::int
          from products p where {predicate}""").fetchone()
        rows=conn.execute("""select p.id::text,p.ean,p.artist,p.title,p.metadata_source,p.metadata_status,
          count(pr.id) filter(where pr.is_active and pr.last_seen_at>=now()-interval '48 hours')::int active_offers
          from products p left join prices pr on pr.product_id=p.id
          where p.title is null or btrim(p.title)='' or p.artist is null or btrim(p.artist)=''
             or p.title ~* '^(vinyl|lp|record)( (ean|upc))? [0-9]{8,14}$'
             or p.title ~ '^[0-9]{8,14}$' or p.title ~* '^unknown( (album|title|artist))?$'
             or p.artist ~* '^unknown artist$'
          group by p.id order by active_offers desc,p.id limit %s""",(max(1,min(a.limit,50000)),)).fetchall()
        out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("w",newline="",encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["product_id","ean","artist","current_title","metadata_source","metadata_status","active_offers","action"])
            for r in rows: w.writerow([*r,"review"])
        repaired=0
        if a.repair_qotsa:
            row=conn.execute("select ean,artist,title from products where id=%s for update",(QOTSA_ID,)).fetchone()
            if not row or row[0]!=QOTSA_EAN or not technical(row[2]): raise SystemExit("QOTSA repair guard failed")
            conn.execute("""update products set artist='Queens of the Stone Age',title='Alive in the Catacombs',
              artist_normalized='queens of the stone age',title_normalized='alive in the catacombs',
              canonical_key='queens-of-the-stone-age::alive-in-the-catacombs',
              search_text='queens of the stone age alive in the catacombs 0191401214230 00191401214230',
              metadata_source='manual_verified',metadata_status='verified',metadata_confidence=100,
              metadata_needs_review=false,updated_at=now() where id=%s""",(QOTSA_ID,)); repaired=1
        if a.repair_qotsa: conn.commit()
        else: conn.rollback()
        print(json.dumps({"status":"written" if a.repair_qotsa else "audit_only","total_flagged":totals[0],
          "total_with_active_offers":totals[1],"reported":len(rows),"reported_active_offers":sum(r[6] for r in rows),
          "repaired":repaired,"report":str(out)}))
if __name__=="__main__": main()
