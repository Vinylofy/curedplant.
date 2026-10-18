# EAN/detail quality status

Bijgewerkt: 2026-10-18. Repository: `Vinylofy/curedplant.`.

Dit is het centrale document voor de EAN/detail-kwaliteitscontrole. De review
hieronder betreft de tien eerder rode actions. De achttien eerder groene shops
zijn tijdens deze review niet opnieuw getest.

Uitkomst van deze tien: **acht groen, nul oranje, twee rood**. Samen met de
achttien eerder groene beoordelingen is de geregistreerde stand 26 groen en
twee rood; die eerdere achttien zijn geen nieuwe testresultaten.

## Herstel rode geplande runs van 18 oktober 2026

Vijf rode EAN-runs aangetroffen tijdens deze controle. Het gaat om de volgende
concrete oorzaken; niet iedere rode run betekende nul verzamelde EAN's.

| Shop | Oorspronkelijke rode run | Oorzaak en gerichte reparatie |
| --- | --- | --- |
| Bob's Vinyl | [39099344723](https://github.com/Vinylofy/curedplant./actions/runs/39099344723) — 16 EAN's uit 45 pogingen | Drie verwijderde productlinks gaven 404 en telden als technische fouten, waarna de batch stopte. Ook de standaard productroute van een voorbeeld geeft 404. Alleen bevestigde detail-404/410 worden nu als verwijderd afgehandeld; de batch gaat naar de volgende link. |
| CDHal | [39099405288](https://github.com/Vinylofy/curedplant./actions/runs/39099405288) — 38 EAN's uit 44 pogingen | Oude productlinks, waaronder Weezer – Black Album, geven echt 404. Deze worden apart geteld en in de EAN-wachtrij afgerond. De bestaande browserroute en begrensde 429-vertraging blijven behouden. |
| FiftiesStore | [39101835680](https://github.com/Vinylofy/curedplant./actions/runs/39101835680) — 0 EAN's uit 100 pogingen | De oude parser zocht alleen een Magento `th/td`-tabel. De actuele Hyva-pagina bevat EAN in eigen `td/td`-rijen en `div/div`-specificaties. De parser leest deze productgebonden velden nu ook zonder EAN in de oude queue-payload. Gerelateerde productcodes en tegenstrijdige geldige codes worden geweigerd. Expliciete posters zonder vinyl/LP-aanduiding worden uitgesloten. |
| iMusic | [39102779912](https://github.com/Vinylofy/curedplant./actions/runs/39102779912) — vijf EAN's opgeslagen vóór de fout | Bij het gelijknamige album Love ontbreekt de artiest in `og:title`, maar staat Love wel in de eigen productkop. Die kop wordt nu benut; artiest en albumtitel blijven afzonderlijke velden. De oude canonical helper maakte bij twee lege artiestwaarden SQL NULL, in strijd met `products.artist NOT NULL`. Onvolledige identiteiten worden nu uitgesteld terwijl de waargenomen EAN behouden blijft; er wordt geen artiest verzonnen. |
| Records on Vinyl | [39105403941](https://github.com/Vinylofy/curedplant./actions/runs/39105403941) — 64 EAN's uit 67 pogingen | Drie verdwenen Shopify-handles gaven 404 op product.js. Van het onderzochte voorbeeld geven de collectie-API, de gewone product-API én de publieke productpagina 404. De adapter gebruikt de native `/products/<handle>.js`-route en handelt verwijderde handles afzonderlijk af. |

### Nieuwe controles en pogingenteller

De functionele code is eerst lokaal getest en daarna op herstelbranch
`fix/ean-runs-2026-10-18` vanuit de bestaande GitHub-actions gestart. Iedere shop:
25 records, `write=false`; dus geen extra productie-productwrites en geen
verandering van de opgeslagen voortgang of het dagbudget.

| Shop | Herstelpoging / maximum | Gecontroleerd | Geldige GTIN | EAN ontbreekt | Verwijderd | Technische fouten | Nieuwe GitHub-run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bob's Vinyl | 1 / 3 | 25 | 14 | 10 | 1 | 0 | [Groen 39105635137](https://github.com/Vinylofy/curedplant./actions/runs/39105635137) |
| CDHal | 1 / 3 | 25 | 20 | 2 | 3 | 0 | [Groen 39105636365](https://github.com/Vinylofy/curedplant./actions/runs/39105636365) |
| FiftiesStore | 1 / 3 | 25 | 19 | 6 | 0 | 0 | [Groen 39105637387](https://github.com/Vinylofy/curedplant./actions/runs/39105637387) |
| iMusic | 1 / 3 | 25 | 25 | 0 | 0 | 0 | [Groen 39105638640](https://github.com/Vinylofy/curedplant./actions/runs/39105638640) |
| Records on Vinyl | 1 / 3 | 25 | 25 | 0 | 0 | 0 | [Groen 39105821042](https://github.com/Vinylofy/curedplant./actions/runs/39105821042) |

De eerste vier bronproeven draaien op commit `a148019`; de afzonderlijke
Records on Vinyl-reparatie en extra databaseproef staan op `2a482cb`.
Het volledige lokale suite-resultaat is **78 tests geslaagd**, inclusief acht
tests met echte tijdelijke Postgres-tabellen. Daarin wordt ook de concrete
lege-artiest-situatie met `NOT NULL` en de echte canonical product-upsert
gecontroleerd. Workflowvalidatie met actionlint, Python-compilatie en
diffcontrole slagen.

### Reeds gemaakte FiftiesStore-missers herstellen

De 98 inhoudelijke missers van de foutieve FiftiesStore-run mogen niet
permanent verdwijnen uit de nieuwe-productwachtrij. Er is daarom een gericht,
idempotent herstel toegevoegd voor uitsluitend actieve FiftiesStore-links
met een opgeslagen versie-1-detailresultaat van **18 oktober 2026**, status
`not_found`, een response-hash en geen EAN of technische fout.

Dit herstel zet alleen hun EAN-wachtrijstatus terug op pending. Raw-bewijs en
het oorspronkelijke resultaat blijven bewaard. Versie-2-resultaten worden
nooit opnieuw aangeboden door deze correctie. De SQL-afbakening en herhaalde
uitvoering zijn getest in de tijdelijke database.

Het herstel gebeurt bij de eerstvolgende write-run waarvoor dagbudget
beschikbaar is. Het dagbudget is vandaag al gereserveerd; dit wordt niet
kunstmatig teruggezet. De normale volgende dagelijkse run kan de gerepareerde
records dus controleren binnen de bestaande limiet van 100. Dit is voorbereid
en lokaal getest, nog geen claim dat die 98 records al opnieuw zijn gescrapet.

HTTP 403/429 en serverfouten blijven fouten. Alleen de hierboven onderzochte
shops behandelen detail-404/410 als verwijderde artikelen. Discovery-404's,
een volledig mislukte EAN-steekproef en onbekende shopfouten worden niet groen
geforceerd. De prijsactions, de daglimiet en de twee geblokkeerde EAN-shops
North End Haarlem / Sounds Venlo zijn niet gewijzigd. Historische rode runs
blijven rood; nieuwe runs nemen de gepubliceerde reparatie over.

## Betekenis van de status

Groen betekent hier: de read-only pilot haalt actuele producten en detaildata
op, heeft minstens drie GTIN's met geldig controlecijfer en geen HTTP-fouten in
de geselecteerde steekproef. Ontbrekende EAN's worden afzonderlijk geteld en
gaan niet als verzonnen of ongeldige codes door. Een lege queue of een preview
zonder netwerkverzoeken is geen geslaagde pilot.

Deze status bewijst de bronpilot, niet een productie-import of database-write.
De oorspronkelijke Actions-tests gebruiken `limit=25, write=false`. De nieuwe
North End- en Venlo-vervolgproeven gebruiken vijf records en blijven read-only. Er zijn geen
planningen toegevoegd en geen Windows-actions uitgezet tijdens die herstelronde.
De daaropvolgende dagelijkse EAN-inrichting staat hieronder.

## Dagelijkse EAN-planning in curedplant., 17 oktober 2026

De 26 geregistreerd groene shops krijgen ieder hun eigen dagelijkse EAN-action
op Ubuntu. North End Haarlem en Sounds Venlo behouden uitsluitend handmatige
starts en heten nu `Curedplant | GEBLOKKEERD | EAN/detail | <shop>`.
De bestaande prijsactions en Windows-planningen zijn hierbij niet gewijzigd.

De dagelijkse worker gebruikt de bestaande shopspecifieke listing- en
detailparsers. Anders dan de oude CSV-pipelines verwerkt deze uitsluitend
EAN-verrijking en productidentiteit: geen prijs-, voorraad- of prijshistoriewrites.
Raw-verrijkingsrecords hebben `price_raw` en `availability_raw` op NULL.

- Per shop maximaal **100 nieuwe productdetailpogingen per Amsterdamse kalenderdag**.
  Dit garandeert geen 100 gevonden of wereldwijd unieke EAN's. Een product
  zonder geldige code telt als gecontroleerd en wordt als misser opgeslagen.
- De database selecteert actieve, nog niet afgehandelde productlinks; reeds
  opgehaalde details en aanwezige raw-EAN's worden overgeslagen. Volgorde:
  eerste ontdekking, daarna vaste recordidentiteit. Een volgende run pakt de volgende set.
- De cataloguspositie en het dagbudget staan duurzaam in
  `.state/ean/<shop>.json` op branch `automation/ean-progress`, onafhankelijk
  van tijdelijke runnerbestanden en artifacts. Per shop kan één EAN-job tegelijk lopen.
  Een corrupte of ontoegankelijke checkpoint veroorzaakt rood, geen reset.
- Nieuwe productlinks worden indien nodig via maximaal tien listingpagina's
  ontdekt. De volgende pagina wordt onthouden. Na het cataloguseinde volgt na
  zeven dagen opnieuw discovery; afgeronde productdetails blijven uitgesloten.
- iMusic en JPC gebruiken hun bestaande databasewachtrij. Zonder nieuwe
  geregistreerde links melden zij `waiting_for_source_registry`; deze wijziging
  bouwt geen nieuwe discovery-crawler voor die twee shops.
- Iedere write-run reserveert vooraf het resterende dagbudget. Ook extra
  handmatige starts kunnen samen de 100 niet overschrijden. Ongebruikte
  gereserveerde plaatsen na een storing blijven die dag verbruikt; de volgende
  Amsterdamse kalenderdag begint een nieuw budget.
- Een vastgelegde technische fout wordt overgeslagen bij de volgende normale
  nieuwe-productrun en blijft zichtbaar voor gericht herstel. HTTP 403/429
  stopt de run. Een crash vóór databasecommit laat alleen een claim achter;
  die vervalt na twee uur, zodat een latere run het onafgemaakte record kan herstellen.
- Handmatige starts hebben standaard `write=false`: wel broncontrole en
  databaselezingen, geen writes of voortgangswijziging. Herhaalde read-only
  tests kunnen daardoor bewust dezelfde nog niet afgehandelde producten tonen.
- Per run staan aantallen, fouten en volgende positie in de Actions-samenvatting;
  productbewijs staat in artifact `daily-ean-<shop>-<run_id>` (14 dagen).

De tijden hieronder zijn UTC; in Nederland één uur later in wintertijd en
twee uur later in zomertijd. GitHub kan geplande starts vertragen.

| EAN-action / shop | Dagelijks UTC | Maximum nieuwe details |
| --- | --- | --- |
| Atthemovies | 00:17 | 100 |
| Bestkeptrecords | 00:24 | 100 |
| Blackvinyl | 00:31 | 100 |
| Bob's Vinyl | 00:38 | 100 |
| Cdhal | 00:45 | 100 |
| Colouredvinyl | 00:52 | 100 |
| Dgmoutlet | 00:59 | 100 |
| Everything Jazz | 01:06 | 100 |
| FiftiesStore | 01:13 | 100 |
| Getbackmusic | 01:20 | 100 |
| iMusic | 01:27 | 100 |
| JPC | 01:34 | 100 |
| My Record Store | 01:41 | 100 |
| Platenzaak | 01:48 | 100 |
| Platomania | 01:55 | 100 |
| Recordsonvinyl | 02:02 | 100 |
| Rockinoutrecords | 02:09 | 100 |
| Shop3345 | 02:16 | 100 |
| Sounds | 02:23 | 100 |
| Sounds Haarlem | 02:30 | 100 |
| Suburban | 02:37 | 100 |
| Topnotch | 02:44 | 100 |
| Variaworld | 02:51 | 100 |
| Vinyleers | 02:58 | 100 |
| Vinylfreaks | 03:05 | 100 |
| Viprecords | 03:12 | 100 |

Validatie: 61 tests geslaagd, inclusief vier echte Postgres-wachtrijtests op
een tijdelijke lokale database. Bewezen: 100 + 100 verschillende producten,
60 + 40 + 0 binnen één dag, hervatten na crash, behoud van voortgang na
rediscovery, NULL-prijs/voorraad in raw-verrijking en rollback bij productfout.
Workflowvalidatie met actionlint en Python-compilatie slagen.

Begrensde live ontwikkelproef van de nieuwe adapters: 24 shops kregen maximaal
één listing- en één detailaanvraag; 22 details opgehaald, waarvan 20 met geldige
GTIN en twee zonder (FiftiesStore en VIP Records). Rockin Out Records en Vinyl
Freaks gaven bij deze lokale HTTP-proef 403; dit is geen nieuw GitHub-bewijs.
iMusic/JPC zijn in deze bronproef niet aangevraagd vanwege hun bestaande
registratiewachtrij. De eerdere 26 groene beoordelingen zijn dus geen claim dat
alle 26 nieuwe productieplanningen al succesvol hebben gedraaid.

### GitHub-controle van de dagelijkse EAN-lane

Codecommit `dd6497f` staat op `main`; de voortgangsbranch bestaat. Eerste
begrensde GitHub-tests (alleen EAN, geen prijsactions gestart):

| Shop | Nieuwe details / geldige GTIN | Bevinding | Run |
| --- | --- | --- | --- |
| Rockin Out Records | 1 / 1 | Listing en detail beide HTTP 200 vanuit GitHub; read-only geslaagd. Lokale 403 reproduceert hier niet. | [39069440852](https://github.com/Vinylofy/curedplant./actions/runs/39069440852) |
| Vinyl Freaks | 5 / 2 | Alle vijf eigen detailpagina's opgehaald; drie terecht zonder geldige barcode. De eerste eenrecordproef selecteerde een product zonder geldige EAN en werd rood; deze is niet als bronblokkade geïnterpreteerd. | [39069502791](https://github.com/Vinylofy/curedplant./actions/runs/39069502791) |
| Everything Jazz | 0 / 0 | `waiting`: bestaande queue en de eerste tien cataloguspagina's bevatten geen onbehandelde kandidaten. Reeds afgehandelde producten blijven overgeslagen. Read-only schuift het opgeslagen checkpoint niet op. | [39069439149](https://github.com/Vinylofy/curedplant./actions/runs/39069439149) |

De eerste expliciete Rockin Out write-proef kon het checkpoint met een
reservering van één record opslaan, maar de categorieverbinding kreeg een
connect-timeout voordat discovery of detailverwerking plaatsvond. Er zijn in
die proef geen productdetails geschreven. Het budget bleef zichtbaar bewaard;
zie [39069521570](https://github.com/Vinylofy/curedplant./actions/runs/39069521570).
Dit is een verbindingsfout, geen inhoudelijke EAN-misser. De dagelijkse worker
telt technische detailfouten afzonderlijk van inhoudelijke EAN-missers.

De twee daaropvolgende write-proeven zijn beide inhoudelijk groen. Twee
verschillende GitHub-runners selecteerden verschillende producten uit dezelfde
bewaarde wachtrij, valideerden de barcode en committen de metadata. De tweede
run had geen nieuwe discovery nodig en pakte het volgende onbehandelde record.

| Write-run | Product | GTIN-14 | Dagteller na afloop |
| --- | --- | --- | --- |
| [39069611801](https://github.com/Vinylofy/curedplant./actions/runs/39069611801) | Lady Wray – Cover Girl (LP Pink Vinyl) | 00349223016659 | 2 gereserveerd (inclusief de eerdere mislukte verbinding) |
| [39069693233](https://github.com/Vinylofy/curedplant./actions/runs/39069693233) | Timbaland – Best Of (LP Gold Vinyl) | 08717662596087 | 3 gereserveerd |

Beide: één detailpoging, één geldige EAN, geen fouten en nul prijswrites.
Het opgeslagen checkpoint is daarna onafhankelijk via de GitHub API gelezen:
cataloguspagina 2, dagbudget 3, laatste uitkomst groen. Hiermee zijn de
werkelijke repositoryrechten, databasewrite en hervatting vanuit een volgende
runner bewezen voor Rockin Out. Dit is geen claim van 26 geslaagde write-runs;
de overige ingeplande shops gebruiken dezelfde geteste voortgangslaag en hun
eigen adapters.

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
| North End Haarlem | Rood — toegang geblokkeerd na drie vervolgvarianten | 0 / 0 vanuit GitHub | Laatste variant: categorie via HTTP 403, homepage via browser met Windows-profiel eveneens Cloudflare 403. Lokaal met oude broncode 5/5 details en vier geldige GTIN's. | [39066854696](https://github.com/Vinylofy/curedplant./actions/runs/39066854696) |
| Sounds Venlo | Rood — detailtoegang geblokkeerd; EAN-identiteitsfout hersteld | 0 / 0 vanuit GitHub | Catalogus via browser 200; vijf producten geselecteerd. Ook echte catalogusklik naar eerste detail geeft Cloudflare 403. Lokaal 5/5 details, vier correcte GTIN's en één terecht lege EAN. | [39066857022](https://github.com/Vinylofy/curedplant./actions/runs/39066857022) |

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
- Eerste herstelronde North End Haarlem en Sounds Venlo: drie transportvarianten getest (normale HTTP, gewone Chromium, Chromium met eenmaal acht seconden laadtijd). Alle drie werden vanuit GitHub door Cloudflare geweigerd. De expliciet gevraagde vervolgronden staan hieronder; er is geen automatische herstart ingepland.

Voor North End Haarlem en Sounds Venlo is gezamenlijk vervolg nodig: toegang
voor de GitHub-runner met de shop afstemmen, of een toegestane andere runner
kiezen en daar eerst dezelfde read-only pilot draaien. Meer parserwijzigingen
lossen de aangetoonde Cloudflare-blokkade niet op.

## Productiegrenzen en controles

- De eerdere expliciete write-runs gebruikten native shop-workers; de voorafgaande
  registratie ververst uitsluitend een begrensde set productlinks. Die stap
  wijzigt geen publieke prijzen en delist geen ontbrekende catalogusproducten.
- Voor FiftiesStore is delisten op basis van de begrensde EAN-steekproef uitgezet.
- Shop3345 schrijft vanuit de detailworker uitsluitend verrijking; raw-prijs en
  raw-voorraad blijven null. `stock_shop3345` blijft de voorraadautoriteit.
- HTTP-blokkades bij North End tellen niet meer als een inhoudelijke EAN-misser.
- Eenenveertig unittests slagen, inclusief prijsisolatie, echte dry-run-detailaanvragen,
  database-writegrenzen en EUR-marktkeuze. Python-compilatie en diffcontrole slagen.

## North End: expliciet heropende herstelronde, 17 oktober 2026

Op nieuw verzoek van de gebruiker is North End opnieuw onderzocht. De eerdere
drie mislukte proeven eindigden in
[run 39014775460](https://github.com/Vinylofy/curedplant./actions/runs/39014775460).
Deze vervolgronde is afzonderlijk gelabeld als repair_cycle=2, attempt=1.

Nieuwe codeverbeteringen:

- Eén HTTP-/browsersessie per batch voor behoud van first-party cookies. De
  gewone browser begint bij de homepage en gebruikt daarna dezelfde pagina.
- Minimaal 30 seconden tussen documentaanvragen, overeenkomstig de door de shop
  gepubliceerde Crawl-delay. Een blijvende 403 of 429 stopt verdere aanvragen.
- Barcode alleen uit de specificatietabel van het eigen product. De globale
  afkapping op woorden zoals "Meer" en "Menu" is verwijderd; ongeldige
  controlecijfers of verschillende productcodes worden geweigerd.
- Ook de waargenomen detailprijs wordt tot het eigen prijsblok beperkt.
- Bij listingproblemen wordt een fout doorgegeven in plaats van stil met een
  onvolledige catalogus door te gaan. Beide North End-lanes hebben browserondersteuning.

De gepubliceerde RSS-route is onderzocht. Deze bevat navigatie-/categorielinks,
geen productprijzen of EAN-feed en vervangt dus de detailpagina's niet.

Lokale liveproef: 3/3 detailpagina's HTTP 200; twee geldige GTIN's en één ontbrekende
geldige barcode. Dezelfde verbeterde code is met een limiet van vijf records getest in
[Action 39064461985](https://github.com/Vinylofy/curedplant./actions/runs/39064461985).
Definitieve GitHub-uitkomst: rood. De categorie-aanvraag met de HTTP-sessie geeft
403 met cf-mitigated=challenge. Na de wachttijd geeft ook de normale
browsernavigatie naar de homepage 403 met dezelfde challenge-markering. De
batch stopt daarop; er zijn geen detailpagina's aangevraagd en geen verdere
automatische pogingen ingepland. Databasewrites: nul.

## Sounds Venlo: hernieuwde bronreview, 17 oktober 2026

Deze expliciet gevraagde vervolgronde is repair_cycle=2, attempt=1. De actuele
catalogusroute `/vinyl/` werkt vanuit de ontwikkelomgeving en de pagina bevat
de verwachte vervolglinks `/vinyl/p2/`, `/vinyl/p3/`. De robots-instructies
publiceren een Crawl-delay van tien seconden en een sitemap; er is geen
productfeed met EAN's gevonden in de onderzochte pagina's.

Er is naast de eerdere Cloudflare-blokkade een concrete identiteitsfout bewezen:
op de pagina van Fresku – Leren Leven (`/4707526-fresku-leren-leven/`) stond
geen eigen barcode in het productblok of Product-JSON-LD. De oude parser koos
`0602475004783` uit een afbeelding van het gerelateerde album In Het Diepe
(`/4704205-fresku-in-het-diepe/`). De eerdere lokale beoordeling van drie
EAN-hits was hierdoor te ruim en is geen bewijs van drie correcte matches.

Hersteld in code:

- Geen algemene scan meer op lange nummers in alle HTML of afbeeldingsnamen.
- EAN uitsluitend uit het eigen productblok, Product-JSON-LD met dezelfde URL
  of een geldige code in de eigen product-URL. Controlecijfer verplicht;
  verschillende geldige codes geven geen willekeurig gekozen match.
- Interne product-ID's van zeven cijfers worden niet als barcode gebruikt.
- Genre, formaat, release en intern product-ID blijven in het eigen productblok;
  een niet vermelde platenmaatschappij blijft leeg.
- Eén HTTP-/browsersessie per batch, tien seconden tussen documentaanvragen,
  en stop bij blijvende 403/429. Beide worker-lanes hebben browserondersteuning.

Lokale liveproef met vijf records: alle vijf detailpagina's HTTP 200,
vier geldige productgebonden GTIN's, één terecht lege EAN, geen databasewrites.

| Product | Gevalideerde GTIN-14 | Bewijsbron |
| --- | --- | --- |
| Fresku – Leren Leven | Geen | Eigen product heeft geen geldige barcode; code van gerelateerd album geweigerd |
| America – Holiday Harmony | 00792755872161 | Eigen zichtbare productmetadata |
| Various – Sinister Sounds Of Halloween Horror | 00826853007580 | Eigen zichtbare productmetadata |
| Kikagaku Moyo – Masana Temples | 00606825444120 | Eigen metadata en product-URL `/0606825444120-4357567/` stemmen overeen |
| Kikagaku Moyo – Forest Of Lost Children | 09504281135228 | Eigen zichtbare productmetadata |

Bronverschil zichtbaar gemaakt: America staat in de listing als in_stock,
maar de eigen Product-JSON-LD zegt BackOrder. De detailworker verandert daarom
geen publieke prijs/voorraad op basis van die andere bron; beide waarnemingen
staan in het pilotbewijs.

De read-only GitHub-proef met een limiet van vijf records staat in
[Action 39065075856](https://github.com/Vinylofy/curedplant./actions/runs/39065075856).
Definitieve GitHub-uitkomst: rood. De HTTP-aanvraag op /vinyl/ en daarna de
normale browseraanvraag op de homepage geven beide HTTP 403 met expliciete
cf-mitigated=challenge. De sessie stopt daarop; geen verdere categorie- of
detailaanvragen, geen databasewrites en geen aanvullende automatische pogingen.
De productparser is lokaal aantoonbaar verbeterd, maar de runner-toegang is
niet opgelost door deze codewijziging.

## Linux-proef met de werkende Windows-broncode, 17 oktober 2026

Op verzoek zijn de vier oorspronkelijke bronbestanden (listing en detail per
shop) ongewijzigd gekopieerd uit Vinylofy/Vinylofy commit
`c4b86b475c3af219b5f5dee77335c625af24605f`. Dat is de bronversie van de vandaag
geslaagde Windows-runs [North End 39015584821](https://github.com/Vinylofy/Vinylofy/actions/runs/39015584821)
en [Sounds Venlo 39029778437](https://github.com/Vinylofy/Vinylofy/actions/runs/39029778437).
De Windows-prijslogs bewijzen respectievelijk 4.618 en 20.357 catalogusrecords;
276 en 10.702 bestaande prijzen verwerkt. Dit is geen nieuwe EAN-goedkeuring.

De vier bestaande handmatige Linux-actions hebben nu de keuze
`source_version=windows-baseline` of `current` (standaard voor EAN). De baseline draait
op Ubuntu/Python 3.11, gebruikt de originele fetch- en parserfuncties en
controleert vóór import de SHA-256-hashes in
`scripts/workers/windows_baseline/manifest.json`. Gedeelde USF-helpers en
dependencies komen uit curedplant.; hun runtimeversies staan in het bewijs.
De Windows-machine en zijn netwerk worden hierdoor niet gereproduceerd.

De aparte testworker roept geen native database-pipeline aan. Writes worden in
de workflow en CLI geweigerd en DATABASE_URL wordt niet aan de baseline-job
doorgegeven. Limieten: één tot drie listingpagina's (North End alleen de eerste
categorie), maximaal 25 details uit de eerste listingpagina, één native poging
per fetch en 30/10 seconden tussen aanvragen. De oorspronkelijke gewone
Venlo-browserfallback blijft behouden; bij 429 stopt de proef. De twee lanes
worden per shop achter elkaar uitgevoerd. Planning en Windows-activatie zijn
niet gewijzigd.

Een baseline-EAN wordt vergeleken met de herstelde productgebonden parser;
afwijkingen worden opgeslagen en veroorzaken rood. Zo wordt de oude verkeerde
albumkoppeling niet stil opnieuw goedgekeurd. De lokale Venlo-proef heeft vijf
details opgehaald, vier overeenstemmende GTIN's en de eerder bewezen verkeerde
Fresku-code afzonderlijk afgewezen. Bron bereikbaar, kwaliteit baseline rood.
Dit is een Linux-ontwikkelproef op Python 3.12, nog geen hosted-runnerbewijs.

De lokale North End-baseline haalt vijf details op: vier overeenstemmende
GTIN's, één ontbrekende geldige barcode, geen parserafwijkingen of HTTP-fouten.
Dit is een geslaagde ontwikkelproef, nog geen geslaagde hosted-runnerproef.

De vier oorspronkelijke-bronproeven op GitHub zijn afgerond (Ubuntu, Python
3.11.17). Alle vier: write=false, nul databasewrites.

| Shop / lane | Uitkomst | Bewijs |
| --- | --- | --- |
| North End / prijs | Rood, categorie HTTP 403 met de oorspronkelijke HTTP-code | [39066105289](https://github.com/Vinylofy/curedplant./actions/runs/39066105289) |
| North End / detail | Rood, categorie HTTP 403; geen details aangevraagd | [39066106839](https://github.com/Vinylofy/curedplant./actions/runs/39066106839) |
| Sounds Venlo / prijs | Groen, 50 producten met prijzen; HTTP 403 maar oorspronkelijke browserroute levert de listing | [39066108321](https://github.com/Vinylofy/curedplant./actions/runs/39066108321) |
| Sounds Venlo / detail | Rood, listing via browser werkt; oude detailworker gebruikt weer HTTP en krijgt 403 op het eerste product | [39066110319](https://github.com/Vinylofy/curedplant./actions/runs/39066110319) |

De Venlo-prijsproef bewijst dat hosted Linux toegang kan krijgen via de oude
browserroute. Alleen IP of besturingssysteem aanwijzen als oorzaak is dus te
stellig. De verbeterde current-variant neemt nu per shop de oorspronkelijke
HTTP-/browserheaders over, navigeert direct naar de gevraagde categorie (geen
verplichte homepage) en houdt de gewone browsersessie ook voor details aan.
De correcte productgebonden EAN-parser blijft behouden. Dit is een tweede,
afzonderlijke gerichte vervolgvariant; de bronkopieën blijven ongewijzigd.
Deze tweede current-vervolgvariant is voor EAN/detail op GitHub getest:

- [North End 39066397769](https://github.com/Vinylofy/curedplant./actions/runs/39066397769):
  categorie met HTTP én directe browsernavigatie geeft Cloudflare 403; nul details.
- [Sounds Venlo 39066401105](https://github.com/Vinylofy/curedplant./actions/runs/39066401105):
  categorie via browser geeft 200 en vijf geselecteerde producten; eerste directe
  browsernavigatie naar Fresku geeft Cloudflare 403; nul opgehaalde details.

De derde en laatste EAN-vervolgvariant gebruikt echte cataloguslinks: de browser
klikt de bestaande productanker aan en keert voor een volgend product zo nodig
naar de catalogus terug. De browser verzorgt zelf de normale verwijzende pagina;
er wordt geen vaste Referer-header voor alle documenten gebruikt. North End
begint voor deze variant bij de homepage met het Windows-profiel en volgt de
categorielink; een geblokkeerde homepage beëindigt de proef direct. Venlo begint
bij de bewezen bereikbare listing. Wachtintervallen en stoppen bij 403/429 blijven
behouden. Vervolgvalidatie is uitsluitend EAN/detail, zonder prijsherstarts.

De echte Chromium-navigatie is lokaal getest met onderschepte fixture-antwoorden:
catalogus → product 1 → catalogus → product 2, vier documenten, beide product-
requests hebben de catalogus als Referer. Deze check bereikt de shops niet en
bewijst de browserbediening, niet de toegang vanuit GitHub. De definitieve
shopuitkomsten van variant drie staan hieronder.

### Definitieve EAN-uitkomst van de derde vervolgvariant

Beide runs zijn afgerond op codecommit `678ec14`, zonder databasewrites.

| Shop | Geselecteerd / details / geldige GTIN | Laatste bewezen punt | Bewijs |
| --- | --- | --- | --- |
| North End Haarlem | 0 / 0 / 0 | HTTP-aanvraag categorie 403; gewone browser met Windows-profiel geeft op homepage ook 403 met cf-mitigated=challenge. Daarna gestopt. | [39066854696](https://github.com/Vinylofy/curedplant./actions/runs/39066854696) |
| Sounds Venlo | 5 / 0 / 0 | Listing via browser 200. Bestaande catalogusanker naar Fresku echt aangeklikt (`navigation=link`); detailresponse 403 met cf-mitigated=challenge. Daarna gestopt. | [39066857022](https://github.com/Vinylofy/curedplant./actions/runs/39066857022) |

Status blijft voor beide rood. Er zijn geen verdere herstelpogingen gestart,
geen EAN-planningen aangezet en geen Windows-runners uitgezet. De eerdere
Venlo-prijsproef is uitsluitend bewijs voor de bereikbare listing, geen EAN-
goedkeuring. Voor verdere EAN-validatie is toegang tot productdetails vanuit
de runner nodig, bijvoorbeeld via een met de shop afgestemde toegang of feed.

Bewijs: JSON-artifact `windows-baseline-<shop>-<lane>-<run_id>`, met product-URL,
listingprijs, oude en gevalideerde EAN, response-hash, transportstatus,
broncommit en nul databasewrites. De eenenveertig tests en actionlint-controle
van de zes gewijzigde workflowbestanden slagen.

## Eerder vastgelegde groene resultaten

- Platenzaak: 14 geldige EAN's uit 17 kandidaat-records; drie missers.
- Platomania: 25/25 records geaccepteerd door de importer.
- Records on Vinyl: 23/25 geaccepteerd; twee afgewezen.
- Sounds: 25/25 detailpagina's met EAN in de read-only pilot.
- De overige eerder groene shops behouden hun bestaande beoordeling; hier is
  geen nieuwe test of productievalidatie voor geclaimd.
