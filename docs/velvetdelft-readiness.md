# Velvet Delft — brononderzoek en readiness

Status: **EAN-automatisering actief; databasepublicatie nog niet vrijgegeven.**

Geïntegreerd op `main`, via [PR #2](https://github.com/Vinylofy/curedplant./pull/2). Frontend en bestaande shops zijn niet aangepast. Het slug `velvetdelft` is toegevoegd aan de importerregistry en als **disabled** USF-shop geregistreerd; de bestaande productiedatabase-registratie is niet onderzocht of gewijzigd.

## Geautoriseerde EAN-automatisering — 2 november 2026

De gebruiker heeft de EAN-controles nu expliciet geautomatiseerd: **dagelijks maximaal 1.000 checks tot alle ontdekte releases hun eerste detailcontrole hebben gehad; daarna maximaal 250 roulerende hercontroles per week**. Dit geeft geen toestemming voor databasepublicatie of prijscron. De vier onbetrouwbare collectietellingen blijven bronreviewpunten.

Eén EAN-workflow heeft een dagelijkse trigger om **05:17 UTC** (06:17 Nederlandse wintertijd, 07:17 zomertijd). Tijdens onderhoud slaat de planner dagen over zonder de winkel te benaderen; na zeven kalenderdagen in Europe/Amsterdam komen maximaal 250 oudste detailwaarnemingen aan de beurt. Nieuwe onbehandelde releases zetten de dagelijkse eerste ronde weer aan. Ook ontbrekende/afgekeurde EANs tellen als gecontroleerd; ze blokkeren de overgang naar onderhoud niet. Een HTTP-blokkade geldt niet als afgeronde inhoudelijke controle en stopt bronverkeer.

Er wordt slechts één artikel tegelijk opgehaald, minimaal drie seconden tussen aanvragen. Bij 1.000 checks duurt alleen de wachttijd ongeveer 50 minuten; de bronrun stopt zacht na 70 minuten en de job heeft 90 minuten om checkpoints/artifacts af te handelen. Bij trage responses kan een dag minder dan 1.000 checks halen; de volgende dag pakt het checkpoint verder. De dagteller voorkomt meer dan 1.000 automatische checks door herstarten; een onderbroken onderhoudsronde hervat het resterende weekbudget van 250.

De broncheckpoint wordt duurzaam bewaard in `state/velvetdelft/checkpoint.json.gz` via een aparte stap met alleen repository-schrijfrechten. De scraper zelf ontvangt geen GitHub-token of databasegeheimen. Voor het eerste websiteverzoek wordt de duurzame opslag gecontroleerd. De cache blijft een herstelmiddel; de nieuwste bewaarde bronversie wint bij herstel. Dit voorkomt een reset wanneer een wekelijkse Actions-cache verloopt. Artifacts blijven 90 dagen beschikbaar. Een bron-/opslagfout wordt rood gemeld; er is geen agressieve herstartketen.

**Daadwerkelijk gestart:** [eerste automatische ronde 41429886010](https://github.com/Vinylofy/curedplant./actions/runs/41429886010). De runner heeft planning, tests en het duurzaam schrijven van de broncheckpoint succesvol afgerond en is bezig met de detailcontroles. Deze run is nog niet als afgerond of inhoudelijk groen aangemerkt. Negen extra plannertests zijn geslaagd; de bestaande acht PostgreSQL-tests blijven de eerdere databasevalidatie.

De voorwaarden voor productiepublicatie blijven onveranderd: alle gates, actuele listingprijzen, productieregistratie en een afzonderlijke write-goedkeuring. Een geslaagde automatische EAN-run bewijst geen productie-import.

## Werkelijke bron en paginering

Er is geen volledige centrale vinylcatalogus bewezen. De bron bestaat uit de 13 werkelijke genre-URL’s en aanvullende releases/actiecollecties hieronder. De eerste HTML bevat productkaarten en filters. De paginalinks zijn JavaScript-triggers: gewone GET-requests met `?page=2` gaven bij Prog en Jazz opnieuw pagina 1. De website zelf gebruikt **POST https://www.velvetdelft.nl/products/blockitems**, met het publieke `blockid`, genre-/tagfilters, een normale sessie-CSRF-header en een paginanummer. Dit endpoint is toegestaan door de gecontroleerde robots.txt; zoekroutes, API, account, cart en afbeeldingen worden niet bezocht. Geen blokkade-omzeiling.

Filter-ID’s zijn rechtstreeks gecontroleerd tegen zichtbare formatlabels: **5 = 10-inch, 6 = LP, 7 = 12-inch maxi-single, 11 = 7-inch single**. De payload hergebruikt bronfilters en vraagt deze vinyltypen; iedere kaart wordt vervolgens opnieuw op een eenduidig vinylformaat gecontroleerd. `instockonly=false` behoudt leveranciersaanbod. De bestaande publieke parameter `p=true` maakt paginering ook beschikbaar op genres die deze in hun UI verbergen. De gekozen paginaomvang komt uit broncontrols (48/192); de server leverde soms maximaal 100 kaarten per response. De scraper gebruikt de werkelijk teruggegeven aantallen, geen aangenomen page size.

Robots: https://www.velvetdelft.nl/robots.txt. Algemene voorwaarden: https://www.velvetdelft.nl/nl/pagina/algemene-voorwaarden. Het robots-sitemapadres wijst naar LPos, niet naar een bewezen complete Velvet-catalogus; het is daarom niet als catalogus gebruikt. De 13 voorafgaande probe-slugs zijn gecorrigeerd, waaronder Dance, Heavy en K-Pop.

## Gevonden dekking

**9,285 unieke vinylrelease-ID’s** zijn daadwerkelijk opgeslagen; een geschat volledig winkelbestand is **onbekend**. Alle 13 genres zijn tot hun laatste getelde pagina doorlopen. De som van categorieën bevat overlap en is geen unieke totaaltelling. Vier tagcollecties melden foutief één resultaat en blijven als onvolledig gemarkeerd. Aanvullende pagina-2-proeven op Indie en Black Friday waren leeg, maar bewijzen geen onbekende globale serverlimiet weg. Er wordt niets gedelist of verwijderd.

| Categorie | URL | Pagina’s | Bron-ID’s | Dekking |
|---|---|---:|---:|---|
| home | [bron](https://www.velvetdelft.nl/nl) | 1 | 14 | Doorlopen |
| countryblues | [bron](https://www.velvetdelft.nl/nl/pagina/countryblues) | 3 | 121 | Doorlopen |
| danceelektronisch | [bron](https://www.velvetdelft.nl/nl/pagina/danceelektronisch) | 3 | 284 | Doorlopen |
| heavy-metal | [bron](https://www.velvetdelft.nl/nl/pagina/heavy-metal) | 6 | 537 | Doorlopen |
| hip-hop | [bron](https://www.velvetdelft.nl/nl/pagina/hip-hop) | 9 | 881 | Doorlopen |
| jazz | [bron](https://www.velvetdelft.nl/nl/pagina/jazz) | 11 | 497 | Doorlopen |
| kpop | [bron](https://www.velvetdelft.nl/nl/pagina/kpop) | 1 | 59 | Doorlopen |
| nederlands | [bron](https://www.velvetdelft.nl/nl/pagina/nederlands) | 3 | 258 | Doorlopen |
| poprock | [bron](https://www.velvetdelft.nl/nl/pagina/poprock) | 44 | 4316 | Doorlopen |
| prog | [bron](https://www.velvetdelft.nl/nl/pagina/prog) | 3 | 271 | Doorlopen |
| reggae | [bron](https://www.velvetdelft.nl/nl/pagina/reggae) | 2 | 132 | Doorlopen |
| soulrnb | [bron](https://www.velvetdelft.nl/nl/pagina/soulrnb) | 5 | 411 | Doorlopen |
| soundtracks | [bron](https://www.velvetdelft.nl/nl/pagina/soundtracks) | 6 | 503 | Doorlopen |
| wereld | [bron](https://www.velvetdelft.nl/nl/pagina/wereld) | 9 | 824 | Doorlopen |
| nieuw-binnen | [bron](https://www.velvetdelft.nl/nl/pagina/nieuw-binnen) | 2 | 155 | Doorlopen |
| vinyl-sale | [bron](https://www.velvetdelft.nl/nl/pagina/vinyl-sale) | 8 | 778 | Doorlopen |
| speciale-uitgaven | [bron](https://www.velvetdelft.nl/nl/pagina/speciale-uitgaven) | 1 | 100 | Totaaltelling onbewezen |
| Gekleurd-vinyl-actie | [bron](https://www.velvetdelft.nl/nl/pagina/Gekleurd-vinyl-actie) | 1 | 25 | Totaaltelling onbewezen |
| black-friday-special-releases | [bron](https://www.velvetdelft.nl/nl/pagina/black-friday-special-releases) | 1 | 92 | Totaaltelling onbewezen |
| national-album-day-2026 | [bron](https://www.velvetdelft.nl/nl/pagina/national-album-day-2026) | 1 | 24 | Totaaltelling onbewezen |

LP, 7-inch, 10-inch en 12-inch zijn daadwerkelijk gevonden en in de 100-detailtest opgenomen. Nieuwe releases, Vinyl Sale, Indie Only, Velvet Exclusives, Black Friday en National Album Day zijn onderzocht. Er is in de opgenomen listings geen expliciete preorderstatus gevonden; toekomstige/ongeprijsde items worden niet als direct bestelbare voorraad verzonnen. De parser ondersteunt een expliciete preordervermelding; zonder zo’n bronvermelding blijft de waargenomen leveranciers-/onbekende status behouden.

## Kwaliteit en EAN-gate

| Metriek | Uitkomst |
|---|---:|
| Unieke releases in detailsteekproef | 100 |
| Geldige, in het gelabelde detailveld bevestigde GTIN | 100 / 100 (100%) |
| Geldige listingprijs in steekproef | 92 / 100 (92%) |
| Bevestigde beschikbaarheidsklasse in steekproef | 92 / 100 (92%) |
| USF-testpublicaties in geïsoleerde database | 92 |
| Quarantaine in geïsoleerde database | 8 |
| Geldige listingprijs in volledige bronvangst | 9032 / 9285 |
| Extra details in hervatbare cataloguscheckpoint | 10 |
| HTTP 403/429 in geslaagde bron-/detailproeven | 0 |
| Productiewrites / verwijderingen | 0 / 0 |

De 100%-EAN-dekking geldt uitsluitend voor de 100 geselecteerde details, niet voor alle ontdekte releases. De acht niet-publiceerbare steekproefrecords hebben geen bevestigde verkoopprijs/beschikbaarheid. De 564 niet-vinylkaarten uit het eerste gemengde brononderzoek zijn uitgesloten; dit is een waarneming over onderzochte pagina’s, geen unieke winkelbrede telling.

Beschikbaarheid in de catalogus: `{'in_stock': 7558, 'unknown': 289, 'supplier_order': 1438}`. **supplier_order** blijft expliciet in brondata; de gedeelde openbare prijsstructuur ondersteunt die status niet, dus de adapter zet deze conservatief om naar **unknown**, nooit naar **in_stock**. Ongeprijsde records zijn uitgesloten van promotion.

Checksums en GTIN-14 komen uit de bestaande centrale helper. UPC/EAN met equivalente voorloopnullen matchen op GTIN-14. Release-ID en SKU zijn nooit EAN. Conflicterende URL/detail/JSON-LD-identificaties, ongeldige codes, niet-nieuw vinyl en ambiguë bundles worden geweigerd. De bronprijs wordt uitsluitend uit de eigen listingkaart/cartprijs gelezen; doorgestreepte prijzen en verzending worden niet als verkoopprijs gebruikt. Detail leest geen prijs of voorraad. De bestaande MusicBrainz/canonieke metadata worden door de gedeelde product-upsert beschermd.

Steekproeven tegen de werkelijk opgeslagen bronpagina’s:

| Release | Listingprijs | GTIN-14 | Bron |
|---|---:|---|---|
| 150596 | € 15.99 | 00602488050265 | [detail](https://www.velvetdelft.nl/nl/release/150596/Frenna-Shallipopi/7-Zaazaa/Frenna-Shallipopi/1-7-inch-single/602488050265) |
| 544832 | € 19.99 | 08720589667907 | [detail](https://www.velvetdelft.nl/nl/release/544832/Fatal-Flowers/SEVEN-DAYS-TO-REMEMBER/Fatal-Flowers/1-10-inch/8720589667907) |
| 133481 | € 29.99 | 05060944577216 | [detail](https://www.velvetdelft.nl/nl/release/133481/Aphex-Twin/Digeridoo/Aphex-Twin/2-12-inch-maxi-single/5060944577216) |
| 524509 | € onbekend | 04099964275605 | [detail](https://www.velvetdelft.nl/nl/release/524509/IOMMI-TONY/FROM-THE-DARK-Velvet-Exclusive/IOMMI-TONY/2-LP/4099964275605) |
| 534028 | € 49.99 | 00888072804142 | [detail](https://www.velvetdelft.nl/nl/release/534028/Alvin-Dave/Blackjack-david/Alvin-Dave/2-LP/888072804142) |

## USF en herstartbaarheid

De importer heeft een vaste CSV-header, required/optional columns, CanonicalRecord-mapper en registry-entry, met `include_in_all=False`. De shop-adapter gebruikt de bestaande USF-tabellen **scrape_runs → shop_product_links → raw_shop_scrapes → staged_offers / quarantine_offers → products/prices** en hergebruikt link-upsert, staging, promotion-conversie, product-/price-/historyhelpers. Er is geen nieuwe matchingdatabase of frontendroute toegevoegd.

De echte 100-recordset is in een wegwerp-PostgreSQL zonder netwerk door de keten gegaan: 100 raw snapshots, 92 producten/prijzen, acht quarantaineregels. Herhalen maakt geen extra bron/product/prijsregels. De tests beschermen recentere listingwaarnemingen en canonieke metadata, hervatten na een onderbroken promotion en hergebruiken bestaande release-ID’s wanneer een bron-URL wijzigt. Snapshot-fingerprints voorkomen dubbel verwerken. Pending EANs blijven verrijkingswerk, geen definitieve afkeuring.

Publieke workflows hebben geen databasesecrets of database-write-input. Alleen de EAN-workflow heeft na de expliciete toestemming hierboven een cron; Discovery en Price blijven handmatig. De importer-CLI eist `--dry-run`; de muterende USF-testadapter weigert externe databasehosts en vereist expliciet dezelfde geïsoleerde DATABASE_URL. De productiewrite-ingang is bewust nog niet vrijgegeven. Voor livegang moeten registratie/schema en de gewenste begrensde productiepromotie expliciet worden gecontroleerd en goedgekeurd.

## Kosten, planning en gebruik

De hervatbare catalogusvangst registreert 163 requests inclusief hervattingen/ontwikkelcontroles en tien extra details. De afzonderlijke steekproef gebruikte 101 requests (robots + 100 details), naast de beperkte bron-/pagineringresearch. Verzoeken lopen enkelvoudig met minimaal drie seconden interval; alleen 502/503/504 krijgen één vertraagde herhaling. 401/403/429, challenge, onverwachte structuur, herhaalde pagina of tegenstrijdige telling stoppen gecontroleerd met een checkpoint. Session-CSRF/cookies worden niet opgeslagen in artifacts.

De volledige cataloguscheckpoint is als gecomprimeerd bronbewijs opgeslagen, geen actieve publicatielijst. De 100-detailbronset en steekproefquotes zijn ook opgeslagen. Een nieuwe listingcyclus behoudt bevestigde EANs; de initiële ronde controleert onopgeloste records en gewijzigde parserrevisies. De wekelijkse ronde controleert de 250 oudste detailwaarnemingen, ook als hun reguliere vervaldatum nog niet is bereikt. Bevestigde details vervallen na 90 dagen voor hercontrole, ontbrekende/afgekeurde detailresultaten krijgen zeven dagen wachttijd. Nieuwe/onopgeloste releases krijgen voorrang.

Handmatige workflows (Ubuntu):

- `Curedplant | Discovery | Velvet Delft | Manual review`: `max_pages`, `refresh`. Hervat categorie/pagina; voor een nieuwe periodieke cyclus `refresh=true`.
- `Curedplant | Price | Velvet Delft | Manual review`: afzonderlijke listingcyclus; cached EANs blijven behouden.
- `Curedplant | EAN Detail | Velvet Delft | Manual review`: dagelijks maximaal 1.000 initiële checks en daarna wekelijks 250 roulerende hercontroles, met aparte handmatige limiet.
- Gedeelde worker: concurrency `velvetdelft-source`, jobtimeout 90 minuten, zachte bronlimiet 70 minuten, duurzame broncheckpoint, herstelcache en artifacts met 90 dagen retentie.

Bij een lege Actions-cache wordt het beoordeelde broncheckpoint uit deze PR geladen en tegen de opgeslagen SHA-256 gecontroleerd; er is dus geen tweede initiële discovery nodig. Voor nieuwe listings is `refresh=true` beschikbaar; bestaande versheidscontroles blijven gelden.

Alle workflows voeren de offline tests, importer-dry-run en USF-preview uit en tonen tellingen in de Actions-summary. Een poging om de nieuwe Discovery-workflow direct op de featurebranch te starten gaf **HTTP 404**: deze workflow is nog niet op de standaardbranch geregistreerd. Er is dus **geen geslaagde Actions-run** om te linken. Lokaal is na de succesvolle PostgreSQL-tests een extra begrensde read-only detailproef uitgevoerd; tien details uit twee vijf-recordproeven waren geldig, nul databasewrites. Dat was de situatie vóór de aansluitende toestemming: PR #2 is inmiddels gemerged en de eerste automatische EAN-run is daadwerkelijk gestart.

Voorgesteld **na afzonderlijke goedkeuring**: één initiële discovery, dagelijks listing-prijzen, tweemaal per week bounded detailenrichment en periodiek een verse discovery. Een initiële detailbevestiging voor ~9.285 releases kost bij drie seconden per request minimaal ~7,7 uur, te verdelen over circa 38 batches van 250; dagelijkse prijzen mogen daar niet op wachten zodra bestaande EANs bewezen zijn. De EAN-planning is inmiddels geautoriseerd en geactiveerd zoals boven beschreven; prijzen en discovery blijven handmatig.

## Validatie en overgebleven gates

Uitgevoerd: **23 offline tests en acht echte PostgreSQL-tests**; actionlint en `git diff --check`. De SQL-tests gebruikten uitsluitend een wegwerpcontainer met `--network none`, geen Supabase. De 100 opgeslagen detailpagina’s zijn ook opnieuw tegen de strengere JSON-LD-conflictcontrole gevalideerd zonder nieuwe netwerkrequests.

GO: handmatige broncontrole, importerdry-run en geïsoleerde USF-tests. **NO-GO voor databasepublicatie**: de vier foutieve collectietellers verhinderen een claim van volledige winkeldekking; alle overige releases moeten nog door detail-gate; productie-registratie, gecontroleerde write-route en een echte Actions-proef moeten nog worden gecontroleerd na review/merge. Geen schema- of productieauthwijzigingen gedaan.

Gewijzigde onderdelen: `scripts/scrapers/velvetdelft.py`, de bestaande probe, `scripts/importers/import_velvetdelft.py`, importerregistry, disabled USF-shopregistry, `scripts/scrapers/usf/jobs/velvetdelft_pipeline.py`, drie handmatige workflows plus herbruikbare worker, Velvet-tests/fixtures, dit bestaande readinessdocument en machineleesbaar bronbewijs. Andere shops en frontend zijn ongewijzigd.

Bewijs: [kwaliteit/paginering](validation/velvetdelft-20261102.json), [volledige broncheckpoint](validation/velvetdelft-catalogue-20261102.json.gz), [100 echte detailrecords](../tests/fixtures/velvetdelft/sample100.json).
