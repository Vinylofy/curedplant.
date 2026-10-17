# EAN/detail quality status

Laatste controle: 2026-10-17. Een groene GitHub Action betekent alleen dat het
proces technisch eindigde; de kwaliteitsstatus hieronder vereist ook bewezen
catalogus/detail-data.

## Groen

- Platenzaak — 14 geldige EAN's uit 17 kandidaat-records; 3 bronpagina's hadden geen geldige EAN.
- Platomania — 25/25 records geaccepteerd door de importer.
- Records on Vinyl — 23/25 geaccepteerd; 2 records afgewezen door de importer.
- Sounds — 25/25 detailpagina's met EAN in de read-only pilot.
- De eerder groene shops blijven groen volgens de bestaande kwaliteitsregistratie.

## Rood: individueel vervolg nodig

- CDHal — detail werd niet uitgevoerd omdat de read-only pipeline geen registry-rijen mag aanmaken.
- Coloured Vinyl — detailqueue 0; listing/bootstrap ontbreekt in de read-only route.
- DGM Outlet — materialize-queue 0; discovery/bootstrap ontbreekt in de read-only route.
- Everything Jazz — queue 0; eerst listing snapshot/bootstrap nodig.
- FiftiesStore — promote-queue 0; eerst API-listing/bootstrap nodig.
- My Record Store — kandidaten 0; eerst listing snapshot/bootstrap nodig.
- North End Haarlem — detailserver geeft 403; dit is een bronblokkade, geen parserfout.
- Shop3345 — 14 detailpagina's geparsed, maar read-only run slaat opslag bewust over.
- Sounds Haarlem — geregistreerde URL's geven 404; listing snapshot is verouderd.
- Sounds Venlo — 25 records geparsed, maar read-only run slaat opslag bewust over.

## Implementatie

`run_ean_detail.py` voert bij expliciete `write=true` voor deze shops eerst een
shop-specifieke listing-refresh uit. Daardoor wordt de detailqueue niet langer
tegen een verouderde registry gedraaid. Dry-runs blijven volledig read-only.
Een rode kwaliteitsstatus wordt pas groen na een write-run met aantoonbare
EAN-resultaten; een technisch groene Action alleen is daarvoor onvoldoende.
