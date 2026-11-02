# Velvet Delft — actieve productieflow

**Status op 2 november 2026: databasewrites en beide planningen actief op `main` in `Vinylofy/curedplant.`.**

## Daadwerkelijk gecontroleerde uitkomst

| Onderdeel | Aantal |
|---|---:|
| Detailbevestigde EAN-bronrecords in Supabase | 1.010 |
| Shoplinks / raw snapshots / stagingregels | 1.010 elk |
| Aangemaakte prijsregels | 975 |
| Actieve, voor NL zichtbare aanbiedingen | 974 |
| Nieuwe producten via bestaande GTIN-gate | 41 |
| Open quarantainerecords | 36 |

De eerste [echte writerun 41464446761](https://github.com/Vinylofy/curedplant./actions/runs/41464446761) is succesvol afgerond: 1.010 raw snapshots, 975 staging-promoties, 975 prijsregels en 975 historyregels. 41 producten waren nieuw; overige EANs koppelen aan bestaande producten. De bronlistingprijs bepaalt `last_seen_at`, geen kunstmatige actualisering naar het importtijdstip.

35 bevestigde EANs hebben geen bruikbare listingprijs en blijven buiten publicatie. Eén extra aanbieding is afgeschermd wegens een tegenstrijdig bestaand productformaat: **Various Artists — The Women of Def Jam**, GTIN `00602438820405`, bronrelease `106709` (bron: 3-LP; bestaand product: CD). Canonieke metadata zijn behouden. Er is geen product of geschiedenis verwijderd.

Een tussentijdse formaatrestrictie hield ook zeven barcode-geïdentificeerde vinyluitgaven met bonus-CD/DVD tegen. Die regel was te streng. De zeven aanbiedingen zijn gecontroleerd hersteld; alleen het CD-only-conflict blijft vaststaan. Er zijn 43 historische quarantaineregels, waarvan **36 nog open**. De [definitieve controle 41472477713](https://github.com/Vinylofy/curedplant./actions/runs/41472477713) bevestigt **974 EAN + 0 artiest/album = 974 totaal**, status **healthy**.

De NL-marktregistratie is gecontroleerd toegevoegd op basis van de Nederlandse winkel/vestiging en de publieke [PostNL-leveringsvoorwaarden](https://www.velvetdelft.nl/nl/pagina/leveringsvoorwaarden). Alleen NL is bevestigd; kosten en drempels zijn onbekend gebleven. Expliciete uitsluitingen worden niet overschreven. Winkeltype: `physical_record_store`, dus de bestaande UI toont Winkel & Webshop. Geen frontendwijziging of hostingdeploy nodig.

Zichtbaarheid is gecontroleerd op [Taylor Swift — Midnights](https://preview.vinylofy.com/product/e781c6f1-af13-4db8-a322-88a6485722ce?market=NL): HTTP 200, Velvet Music Delft en de eigen winkellink staan daadwerkelijk op de pagina. Dezelfde detailpagina biedt ook andere gekoppelde Midnights-uitvoeringen van Velvet aan.

## Planning en databasewrites

- **Prijs — dagelijks 04:03 UTC:** 05:03 Nederlandse wintertijd / 06:03 zomertijd. Nieuwe listingronde, maximaal 200 pagina’s; bestaande bevestigde EANs worden hergebruikt.
- **EAN/detail — dagelijks 05:17 UTC:** 06:17 Nederlandse wintertijd / 07:17 zomertijd. Maximaal 1.000 eerste detailchecks per Amsterdamse kalenderdag totdat alle ontdekte releases een eerste controle hebben gehad. Daarna maximaal 250 roulerende checks per zeven kalenderdagen.
- Beide workflows hebben standaard **write=true** voor de geautoriseerde planning. Discovery blijft handmatig. De generieke bulk-onboarding wordt niet voor andere winkels geactiveerd.
- Eén bronrequest tegelijk, minimaal drie seconden interval, gezamenlijke concurrency-lock voor Velvet. 403/429/challenges stoppen bronverkeer; geen directe herstartketen of blokkade-omzeiling.

[Hervattingscontrole 41470124095](https://github.com/Vinylofy/curedplant./actions/runs/41470124095) is groen. Het dagbudget van 1.000 was al verbruikt; de eerste batch is hergebruikt voor de database-import. Er zijn daarvoor geen nieuwe 1.000 detailrequests uitgevoerd. De vervolgrun gaat bij de volgende onbehandelde bronregel verder.

De worker controleert databaseverbinding en schrijfrechten vóór nieuwe bronrequests. Het databasegeheim is alleen aanwezig in de afzonderlijke schrijfstappen; de scraper ontvangt het niet. Broncheckpoints staan duurzaam in `state/velvetdelft/checkpoint.json.gz`, met een herstelcache en 90 dagen Actions-artifacts. Dag-/weekbudgetten blijven bij herstart behouden.

De initiële import gebruikte nog de oorspronkelijke schrijflus en kostte circa een half uur. Vervolgruns verwerken uitsluitend nieuwe detailwaarnemingen, zoeken bestaande fingerprints in bulk op en bundelen broninserts via psycopg. Promotion commit in batches van 50, atomisch per batch. De test met de echte 100 bronrecords bewijst herstel na een fout na de eerste 50 gecommitteerde aanbiedingen: de retry schrijft alleen de resterende 42, zonder duplicaten.

Dagelijkse prijsverversing gebruikt de bestaande snelle bulk-prijsschrijver. Eerder geïmporteerde producten worden niet opnieuw door de hele EAN-keten gehaald. Een eerder ongeprijsd artikel kan alsnog via USF promoveren wanneer een valide prijs beschikbaar komt. Alleen waarnemingen uit de huidige listingronde verversen prijzen. Onbekende/leveranciersvoorraad wordt voor Velvet niet als op voorraad behouden. De bestaande standaardwerking voor andere shops is ongewijzigd.

Bronwerk stopt zacht na 55 minuten. EAN-jobs hebben maximaal 120 minuten voor bron, databaseverwerking en bewijs; prijs/discovery 60 minuten, de losse databaseflow 90 minuten. Dit zijn harde plafonds voor één shop. Bij trage responses kan de bronfase minder dan 1.000 checks afronden; de volgende run hervat zonder budgetreset.

## Bron en ontdekte dekking

Er zijn **9.285 unieke vinylrelease-ID’s** opgeslagen in het [beoordeelde broncheckpoint](validation/velvetdelft-catalogue-20261102.json.gz). Dat is discovery, niet een claim dat al 9.285 aanbiedingen zijn gepubliceerd. Alle 13 genres zijn tot hun getelde eindpagina doorlopen. Vier tagcollecties hebben onbetrouwbare totaaltellingen; volledige wereldwijde catalogusdekking blijft onbewezen. Er wordt niets op basis van een onvolledige ronde gedelist.

De echte paginator werkt via publieke **POST `/products/blockitems`**. Gewone GET-paginalinks gaven soms opnieuw pagina 1; de scraper controleert dat. Publieke form controls bevestigen ID 5 = 10-inch, 6 = LP, 7 = 12-inch maxi-single, 11 = 7-inch single. Bronfilters, block-ID en publieke sessie-CSRF worden uit de pagina gelezen; sessiegeheimen worden niet opgeslagen. De robots-toegestane listingroute wordt gebruikt; uitgesloten zoek-, API-, account-, cart- en image-routes worden niet gecrawld.

| Categorie | Pagina’s | Bron-ID’s inclusief overlap | Dekking |
|---|---:|---:|---|
| [home](https://www.velvetdelft.nl/nl) | 1 | 14 | Doorlopen |
| [countryblues](https://www.velvetdelft.nl/nl/pagina/countryblues) | 3 | 121 | Doorlopen |
| [danceelektronisch](https://www.velvetdelft.nl/nl/pagina/danceelektronisch) | 3 | 284 | Doorlopen |
| [heavy-metal](https://www.velvetdelft.nl/nl/pagina/heavy-metal) | 6 | 537 | Doorlopen |
| [hip-hop](https://www.velvetdelft.nl/nl/pagina/hip-hop) | 9 | 881 | Doorlopen |
| [jazz](https://www.velvetdelft.nl/nl/pagina/jazz) | 11 | 497 | Doorlopen |
| [kpop](https://www.velvetdelft.nl/nl/pagina/kpop) | 1 | 59 | Doorlopen |
| [nederlands](https://www.velvetdelft.nl/nl/pagina/nederlands) | 3 | 258 | Doorlopen |
| [poprock](https://www.velvetdelft.nl/nl/pagina/poprock) | 44 | 4316 | Doorlopen |
| [prog](https://www.velvetdelft.nl/nl/pagina/prog) | 3 | 271 | Doorlopen |
| [reggae](https://www.velvetdelft.nl/nl/pagina/reggae) | 2 | 132 | Doorlopen |
| [soulrnb](https://www.velvetdelft.nl/nl/pagina/soulrnb) | 5 | 411 | Doorlopen |
| [soundtracks](https://www.velvetdelft.nl/nl/pagina/soundtracks) | 6 | 503 | Doorlopen |
| [wereld](https://www.velvetdelft.nl/nl/pagina/wereld) | 9 | 824 | Doorlopen |
| [nieuw-binnen](https://www.velvetdelft.nl/nl/pagina/nieuw-binnen) | 2 | 155 | Doorlopen |
| [vinyl-sale](https://www.velvetdelft.nl/nl/pagina/vinyl-sale) | 8 | 778 | Doorlopen |
| [speciale-uitgaven](https://www.velvetdelft.nl/nl/pagina/speciale-uitgaven) | 1 | 100 | Totaal onbewezen |
| [Gekleurd-vinyl-actie](https://www.velvetdelft.nl/nl/pagina/Gekleurd-vinyl-actie) | 1 | 25 | Totaal onbewezen |
| [black-friday-special-releases](https://www.velvetdelft.nl/nl/pagina/black-friday-special-releases) | 1 | 92 | Totaal onbewezen |
| [national-album-day-2026](https://www.velvetdelft.nl/nl/pagina/national-album-day-2026) | 1 | 24 | Totaal onbewezen |

De bronproef van 100 unieke vinylproducten omvat LP, 7-inch, 10-inch en 12-inch, meerdere genres, nieuwe releases, sale en exclusives: 100 geldige gelabelde detail-GTINs; 92 geldige listingprijzen/beschikbaarheden, acht niet publiceerbaar. Die 100%-EAN-dekking geldt voor de steekproef. Het geautomatiseerde vervolg heeft daarna 1.000 extra checks gedaan; opgeslagen bronresultaten zijn herbruikbaar.

## USF en veiligheidsregels

Importcontract en registry leveren een vaste CSV-header en CanonicalRecord. De bestaande USF-structuur blijft leidend: **scrape_runs → shop_product_links → raw_shop_scrapes → staged_offers / quarantine_offers → products / prices / price_history**. Primaire sleutels en centrale barcode-normalisatie voorkomen samenvoeging van verschillende barcodes. Release-ID/SKU is geen EAN.

Listing is uitsluitend leidend voor prijs, saleprijs, EUR, beschikbaarheid, URL en waarnemingstijd. Detail bevestigt EAN en metadata; een detailprijs kan een listingprijs niet overschrijven. Verschillende of ongeldige identificaties en CD-only-conflicten gaan apart. Barcode-geïdentificeerd vinyl met bonusmedia wordt toegelaten. Canonieke/MusicBrainz-metadata en recentere prijzen blijven beschermd.

## Validatie, code en bewijs

**34 offline tests + 19 echte PostgreSQL-integratietests geslaagd**, actionlint en `git diff --check`. De tests gebruiken een wegwerp-PostgreSQL zonder netwerk. Gedekt: echte 100-recordset, checksum/variantconflicten, idempotentie, bron-URL-wijziging, oude prijzen/metadata, batchherstel, snelle prijsupdates, oude bewaarde listings, budgetten, roterende selectie, NL-registratie en respect voor expliciete uitsluitingen.

Gewijzigde onderdelen: Velvet scraper en probe; importer/registries; USF-adapter; EAN-planner/checkpoint; productie-audit en publicatiecontroles; handmatige Discovery, geplande Price en EAN, gedeelde worker en Database-beheerworkflow; tests/fixtures; dit bestaande statusdocument en bron-/databasebewijs. De gedeelde bulk-prijsschrijver heeft alleen een optionele Velvet-instelling; de standaard voor andere shops bleef gelijk. Geen frontendwijziging.

Bewijs: [actuele database-uitkomst en planning](validation/velvetdelft-database-20261102.json), [oorspronkelijke broncontrole](validation/velvetdelft-20261102.json), [100 bronrecords](../tests/fixtures/velvetdelft/sample100.json).


## Extra prijsrun: rapportagecrash hersteld — 2 november 2026

[Run 41481936699](https://github.com/Vinylofy/curedplant./actions/runs/41481936699) ververste en verifieerde **964 prijzen** succesvol. Bron, databasewrites, checkpoint en monitoring waren groen. De afsluitende rapportage faalde met `KeyError: raw_inserted`: de daaropvolgende read-only USF-preview had `database-result.json` overschreven.

De CLI heeft nu aparte standaardbestanden voor write-bewijs (`database-result.json`) en preview (`pipeline-preview.json`); de workflow geeft het previewpad bovendien expliciet mee. Een CLI-regressietest bewijst dat preview het echte schrijfbewijs intact laat. De exacte Actions-summary is lokaal opnieuw uitgevoerd op het uit de runlog herstelde echte 964-resultaat. 35 offline tests, actionlint en diff-check zijn geslaagd; geen databasecode gewijzigd en geen nieuwe volledige scrape gestart voor deze correctie.


### Extra EAN-verrijking hervatten — 2026-11-02

De EAN Detail-workflow heeft een handmatige optie `extra_initial_batch`.
Deze verwerkt maximaal 1000 nog nooit verrijkte artikelen vanuit het nieuwste
checkpoint. Artikelen met een bevestigde barcode of een eerdere detailcontrole
worden overgeslagen, ook bij een gewijzigde parser. Ontbrekende of afgekeurde
EANs blijven beschikbaar voor de afzonderlijke onderhoudsronde.
Na iedere detailcontrole wordt de voortgang opgeslagen. Een volgende extra run
pakt de volgende onbewerkte artikelen. De extra controles hebben een afzonderlijke
teller; de normale dagelijkse 1000 en latere wekelijkse 250 blijven behouden.
Deze hervatting gebruikt de EAN-workflow met database writes aan, geen prijsrun
of herhaling van alleen rapportage. Het rustige tempo en stoppen bij 403/429
blijven actief.
