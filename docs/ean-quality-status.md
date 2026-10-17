# EAN/detail quality status

Bijgewerkt: 2026-10-17. Repository: `Vinylofy/curedplant.`.

Dit is het centrale document voor de EAN/detail-kwaliteitscontrole. De review
hieronder betreft de tien eerder rode actions. De achttien eerder groene shops
zijn tijdens deze review niet opnieuw getest.

Uitkomst van deze tien: **acht groen, nul oranje, twee rood**. Samen met de
achttien eerder groene beoordelingen is de geregistreerde stand 26 groen en
twee rood; die eerdere achttien zijn geen nieuwe testresultaten.

## Betekenis van de status

Groen betekent hier: de read-only pilot haalt actuele producten en detaildata
op, heeft minstens drie GTIN's met geldig controlecijfer en geen HTTP-fouten in
de geselecteerde steekproef. Ontbrekende EAN's worden afzonderlijk geteld en
gaan niet als verzonnen of ongeldige codes door. Een lege queue of een preview
zonder netwerkverzoeken is geen geslaagde pilot.

Deze status bewijst de bronpilot, niet een productie-import of database-write.
Alle onderstaande Actions-tests gebruiken `limit=25, write=false`. Er zijn geen
planningen toegevoegd en geen Windows-actions uitgezet.

## Resultaten per shop

| Shop | Status | Geldige GTIN / opgehaalde details | Herstel / bevinding | Bewijsrun |
| --- | --- | --- | --- | --- |
| CDHal | Groen | 19 / 25 | Directe detailroute vervangt pipeline die dry-run oversloeg; begrensde vertraging bij 429. Zes EAN-missers zichtbaar. | [39014524305](https://github.com/Vinylofy/curedplant./actions/runs/39014524305) |
| Coloured Vinyl | Groen | 24 / 24 | Actuele WooCommerce-listing en eigen detailparser; productie gebruikt de native CLI in plaats van een ongeldige pipeline-optie. | [39014524164](https://github.com/Vinylofy/curedplant./actions/runs/39014524164) |
| Everything Jazz | Groen | 25 / 25 | Actuele collectie-JSON gevolgd door product.js; niet afhankelijk van lege databasequeue voor een test. | [39014524349](https://github.com/Vinylofy/curedplant./actions/runs/39014524349) |
| FiftiesStore | Groen | 12 / 25 | Clerk-productdata en productgebonden Magento-attributen; promote-only route vervangen door daadwerkelijke dataverzameling. Dertien EAN-missers zichtbaar. | [39014525416](https://github.com/Vinylofy/curedplant./actions/runs/39014525416) |
| My Record Store | Groen | 24 / 25 | Nieuwe Tailwind-prijsbadge per eigen producttegel; detailparser werkt. Onvoorwaardelijke raw-write tijdens dry-run hersteld. | [39014525484](https://github.com/Vinylofy/curedplant./actions/runs/39014525484) |
| Shop3345 | Groen | 18 / 18 | Dry-run haalt echt details op. Shopify expliciet EUR: dezelfde LP is 27,99 EUR in plaats van de automatisch gekozen 33,00 USD. Metadata-write kan geen voorraad of publieke prijs publiceren. | [39014775461](https://github.com/Vinylofy/curedplant./actions/runs/39014775461) |
| Sounds Haarlem | Groen | 25 / 25 | Actuele listing vervangt oude 404-productlinks als pilotbron; productie prioriteert recente links. Prijs komt uit productlisting, niet uit volledige paginatekst met verzendkosten. | [39014526535](https://github.com/Vinylofy/curedplant./actions/runs/39014526535) |
| DGM Outlet | Groen | 25 / 25 | EAN komt uit listing-SKU; alle 25 detailaanvragen apart bewezen met response-hash. Dubbele aanvraag verwijderd; HTTP-fouten vallen niet meer stil terug op listingdata. Derde proef geslaagd. | [39014877404](https://github.com/Vinylofy/curedplant./actions/runs/39014877404) |
| North End Haarlem | Rood — na 3 pogingen geblokkeerd | 0 / 0 vanuit GitHub | Cloudflare 403 op de actuele categorie, ook met gewone Chromium-rendering. Lokale bronproef toonde wel werkende parser (2 geldige GTIN's uit 3). | [39014775460](https://github.com/Vinylofy/curedplant./actions/runs/39014775460) |
| Sounds Venlo | Rood — na 3 pogingen geblokkeerd | 0 / 0 vanuit GitHub | Cloudflare 403 op /vinyl/, ook met gewone Chromium-rendering. Lokale bronproef haalde 3/3 geldige GTIN's op. | [39014775514](https://github.com/Vinylofy/curedplant./actions/runs/39014775514) |

Elke nieuwe pilot bewaart een JSON-resultaat en een samenvatting in de Action.
Download op de runpagina het artifact `ean-evidence-<shop>-<run_id>` voor de
product-URL's, titels, geobserveerde en gevalideerde codes, listingprijzen en
eventuele fouten. Artifacts worden 14 dagen bewaard. Het samenvattende bewijs
en de runlinks blijven in dit document staan.

## Begrensde reparaties en resterende blokkades

- CDHal: tweede reparatie; tragere, begrensde requests met EAN-check.
- Coloured Vinyl, Everything Jazz, FiftiesStore, Sounds Haarlem: eerste bron-/routeherstel geslaagd.
- My Record Store: tweede reparatie; gewijzigde prijsmarkup herkend.
- Shop3345: tweede reparatie; expliciete EUR-markt bevestigd vanuit GitHub.
- DGM Outlet: derde en laatste reparatie geslaagd; 25/25 detailresponses met hash en geldige GTIN.
- North End Haarlem en Sounds Venlo: drie transportvarianten getest (normale HTTP, gewone Chromium, Chromium met eenmaal acht seconden laadtijd). Alle drie worden vanuit GitHub door Cloudflare geweigerd. Geen verdere automatische reparatie of herstart ingezet.

Voor North End Haarlem en Sounds Venlo is gezamenlijk vervolg nodig: toegang
voor de GitHub-runner met de shop afstemmen, of een toegestane andere runner
kiezen en daar eerst dezelfde read-only pilot draaien. Meer parserwijzigingen
lossen de aangetoonde Cloudflare-blokkade niet op.

## Productiegrenzen en controles

- Expliciete write-runs gebruiken native shop-workers; de voorafgaande
  registratie ververst uitsluitend een begrensde set productlinks. Die stap
  wijzigt geen publieke prijzen en delist geen ontbrekende catalogusproducten.
- Voor FiftiesStore is delisten op basis van de begrensde EAN-steekproef uitgezet.
- Shop3345 schrijft vanuit de detailworker uitsluitend verrijking; raw-prijs en
  raw-voorraad blijven null. `stock_shop3345` blijft de voorraadautoriteit.
- HTTP-blokkades bij North End tellen niet meer als een inhoudelijke EAN-misser.
- Negen unittests slagen, inclusief prijsisolatie, echte dry-run-detailaanvragen,
  database-writegrenzen en EUR-marktkeuze. Python-compilatie en diffcontrole slagen.

## Eerder vastgelegde groene resultaten

- Platenzaak: 14 geldige EAN's uit 17 kandidaat-records; drie missers.
- Platomania: 25/25 records geaccepteerd door de importer.
- Records on Vinyl: 23/25 geaccepteerd; twee afgewezen.
- Sounds: 25/25 detailpagina's met EAN in de read-only pilot.
- De overige eerder groene shops behouden hun bestaande beoordeling; hier is
  geen nieuwe test of productievalidatie voor geclaimd.
