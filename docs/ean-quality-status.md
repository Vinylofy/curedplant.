# EAN/detail quality status

Bijgewerkt: 2026-10-18. Repository: `Vinylofy/curedplant.`.

Dit is het centrale document voor de EAN/detail-kwaliteitscontrole.
De oorspronkelijke bronreview telt 26 goedgekeurde en twee geblokkeerde shops.
Daarvan zijn achttien eerdere goedkeuringen tijdens de review van tien rode
shops niet opnieuw getest. Deze bronkwalificatie is afzonderlijk van de actuele
operationele kleur hieronder: handmatig groen is nog geen automatisch groen.

## Actuele operationele kleuren volgens de gebruiker

Basismeting: **18-10-2026 09:03 Nederlandse tijd**. Alleen EAN/detail in `curedplant.`.
MOV is later toegevoegd en na bronherstel bijgewerkt: **2 rood, 17 oranje, 10 groen**
in deze tabel. Overige shops zijn bij deze MOV-reparatie niet opnieuw beoordeeld.

- Groen: een automatische run heeft echte records succesvol verwerkt.
- Oranje: bron/code goedgekeurd of handmatig getest; de automatische datarun
  moet dit nog bevestigen. De vijf gerepareerde shops tellen dus als oranje.
- Rood: er staat nog een onopgeloste technische of inhoudelijke blokkade open.

Everything Jazz blijft oranje: GitHub geeft success, maar het eigen resultaat
is `waiting` met nul nieuwe records. Dat is nog geen automatische databevestiging.
De oude rode runs van de vijf gerepareerde shops blijven in Actions staan;
hun actuele reparatiestatus is oranje totdat de automatische run slaagt.

| Kleur | Shop | Bevinding | Laatste automatische run |
| --- | --- | --- | --- |
| Oranje | Music On Vinyl | Native sessies hersteld: Linux-bronproef 25/25 geldige EAN’s, alle verzoeken HTTP 200, nul fouten. Write-proef zonder fouten maar 0 nieuwe details na 10 cataloguspagina’s (waiting); hervatten op pagina 11. Windows-detailplanning blijft actief tot echte succesvolle writes. | [Read-only bronproef 39152893138](https://github.com/Vinylofy/curedplant./actions/runs/39152893138) |
| Rood | North End Haarlem | Producttoegang vanuit GitHub geblokkeerd; geen planning. | Nog geen automatische run |
| Rood | Sounds Venlo | Producttoegang vanuit GitHub geblokkeerd; geen planning. | Nog geen automatische run |
| Oranje | Bob’s Vinyl | Hersteld en handmatig getest; automatische bevestiging van reparatie ontbreekt. | [run 39099344723](https://github.com/Vinylofy/curedplant./actions/runs/39099344723) |
| Oranje | CDHal | Hersteld en handmatig getest; automatische bevestiging van reparatie ontbreekt. | [run 39099405288](https://github.com/Vinylofy/curedplant./actions/runs/39099405288) |
| Oranje | Everything Jazz | Automatische run zonder fouten, maar nul nieuwe records; uitkomst waiting. | [run 39101255623](https://github.com/Vinylofy/curedplant./actions/runs/39101255623) |
| Oranje | FiftiesStore | Hersteld en handmatig getest; automatische bevestiging van reparatie ontbreekt. | [run 39101835680](https://github.com/Vinylofy/curedplant./actions/runs/39101835680) |
| Oranje | Records on Vinyl | Hersteld en handmatig getest; automatische bevestiging van reparatie ontbreekt. | [run 39105403941](https://github.com/Vinylofy/curedplant./actions/runs/39105403941) |
| Oranje | Rockin Out Records | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Shop3345 | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Sounds | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Sounds Haarlem | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Suburban | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | TopNotch | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | VIP Records | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Variaworld | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Vinyl Freaks | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | Vinyleers | Goedgekeurde bron; nog geen geslaagde automatische datarun. | Nog geen automatische run |
| Oranje | iMusic | Hersteld en handmatig getest; automatische bevestiging van reparatie ontbreekt. | [run 39102779912](https://github.com/Vinylofy/curedplant./actions/runs/39102779912) |
| Groen | At the Movies | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39097981243](https://github.com/Vinylofy/curedplant./actions/runs/39097981243) |
| Groen | Best Kept Records | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39098136897](https://github.com/Vinylofy/curedplant./actions/runs/39098136897) |
| Groen | Black Vinyl | Automatisch geslaagd: 89 geldige EAN’s uit 100 details. | [run 39098994515](https://github.com/Vinylofy/curedplant./actions/runs/39098994515) |
| Groen | Coloured Vinyl | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39099793727](https://github.com/Vinylofy/curedplant./actions/runs/39099793727) |
| Groen | DGM Outlet | Automatisch geslaagd: 1 geldige EAN’s uit 1 details. | [run 39100446034](https://github.com/Vinylofy/curedplant./actions/runs/39100446034) |
| Groen | Get Back Music | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39102576354](https://github.com/Vinylofy/curedplant./actions/runs/39102576354) |
| Groen | JPC | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39104215856](https://github.com/Vinylofy/curedplant./actions/runs/39104215856) |
| Groen | My Record Store | Automatisch geslaagd: 100 geldige EAN’s uit 100 details. | [run 39104631185](https://github.com/Vinylofy/curedplant./actions/runs/39104631185) |
| Groen | Platenzaak | Automatisch geslaagd: 5 geldige EAN’s uit 5 details. | [run 39104705803](https://github.com/Vinylofy/curedplant./actions/runs/39104705803) |
| Groen | Platomania | Automatisch geslaagd: 98 geldige EAN’s uit 100 details. | [run 39105403655](https://github.com/Vinylofy/curedplant./actions/runs/39105403655) |

## Extra starts van alle 16 oranje EAN-workers, 18 oktober 2026

Op verzoek zijn alle 16 oranje workers direct extra gestart vanuit `main`,
tussen **09:06 en 09:07 Nederlandse tijd**. Inputs: `limit=100`, `write=true`.
Dit zijn productieruns van de bestaande EAN-workflows, gestart via
`workflow_dispatch`; het zijn geen nieuwe cronregistraties. De dagelijkse
cronplanningen blijven behouden. De twee rode workers zijn niet gestart.

Zes shops hadden vandaag al 100 plaatsen gereserveerd en stoppen daardoor
op `daily_budget_exhausted`: nul extra details en geen automatische
inhoudelijke goedkeuring. Het budget of de voortgang is niet teruggezet.
Voor de overige tien shops is een echte verwerkingsrun gestart; de uitkomst
volgt in de gekoppelde run. Een groene GitHub-run zonder verwerkte records
verandert de operationele kleur niet in groen.

| Shop | Extra run | Dagbudget bij start |
| --- | --- | --- |
| Bob's Vinyl | [39106412701](https://github.com/Vinylofy/curedplant./actions/runs/39106412701) | Al volledig gereserveerd; deze extra start verwerkt niets |
| Cdhal | [39106414307](https://github.com/Vinylofy/curedplant./actions/runs/39106414307) | Al volledig gereserveerd; deze extra start verwerkt niets |
| Everything Jazz | [39106415950](https://github.com/Vinylofy/curedplant./actions/runs/39106415950) | Al volledig gereserveerd; deze extra start verwerkt niets |
| FiftiesStore | [39106417456](https://github.com/Vinylofy/curedplant./actions/runs/39106417456) | Al volledig gereserveerd; deze extra start verwerkt niets |
| iMusic | [39106419014](https://github.com/Vinylofy/curedplant./actions/runs/39106419014) | Al volledig gereserveerd; deze extra start verwerkt niets |
| Recordsonvinyl | [39106426205](https://github.com/Vinylofy/curedplant./actions/runs/39106426205) | Al volledig gereserveerd; deze extra start verwerkt niets |
| Rockinoutrecords | [39106429362](https://github.com/Vinylofy/curedplant./actions/runs/39106429362) | Beschikbaar; verwerkingsrun gestart |
| Shop3345 | [39106431657](https://github.com/Vinylofy/curedplant./actions/runs/39106431657) | Beschikbaar; verwerkingsrun gestart |
| Sounds | [39106434877](https://github.com/Vinylofy/curedplant./actions/runs/39106434877) | Beschikbaar; verwerkingsrun gestart |
| Sounds Haarlem | [39106436198](https://github.com/Vinylofy/curedplant./actions/runs/39106436198) | Beschikbaar; verwerkingsrun gestart |
| Suburban | [39106438019](https://github.com/Vinylofy/curedplant./actions/runs/39106438019) | Beschikbaar; verwerkingsrun gestart |
| Topnotch | [39106439325](https://github.com/Vinylofy/curedplant./actions/runs/39106439325) | Beschikbaar; verwerkingsrun gestart |
| Variaworld | [39106441042](https://github.com/Vinylofy/curedplant./actions/runs/39106441042) | Beschikbaar; verwerkingsrun gestart |
| Vinyleers | [39106442282](https://github.com/Vinylofy/curedplant./actions/runs/39106442282) | Beschikbaar; verwerkingsrun gestart |
| Vinylfreaks | [39106444078](https://github.com/Vinylofy/curedplant./actions/runs/39106444078) | Beschikbaar; verwerkingsrun gestart |
| Viprecords | [39106445717](https://github.com/Vinylofy/curedplant./actions/runs/39106445717) | Beschikbaar; verwerkingsrun gestart |

## Herstel na de gelijktijdige extra starts

De eerste 16 extra starts leverden acht geslaagde verwerkingsruns, zes
budgetstops en twee nieuwe fouten op. Die twee zijn onderzocht:

- Rockin Out [39106429362](https://github.com/Vinylofy/curedplant./actions/runs/39106429362):
  geen details gestart; HTTP 409 bij gelijktijdig opslaan van verschillende
  shopbestanden op dezelfde voortgangsbranch. De drie vaste retries waren
  onvoldoende voor deze startpiek. De code gebruikt nu maximaal tien begrensde
  retries met verschillende wachttijden bij uitsluitend zulke branchconflicten.
  Wijziging van hetzelfde shopbestand blokkeert iedere volgende stale write.
  Een mislukte eerste reservering wordt ook niet meer in `finally` alsnog geschreven.
- Sounds Haarlem [39106436198](https://github.com/Vinylofy/curedplant./actions/runs/39106436198):
  historische productwachtrij met verwijderde handles. Eerste herstelproef:
  24 verwijderde producten en één doorverwijzing naar de homepage uit 25 records,
  dus terecht geen groene EAN-proef. Tweede herstelproef:
  [39107046363](https://github.com/Vinylofy/curedplant./actions/runs/39107046363),
  **25/25 geldige EAN's**, read-only. De worker ontdekt nu eerst een begrensde
  actuele listingpagina en prioriteert recent geziene links. Een homepage na
  productredirect mag geen eigen EAN leveren. Herstelpogingen: 2 van maximaal 3.

Het dagmaximum blijft 100 **gestarte productdetails**. De worker reserveert
vooraf; ongebruikte plaatsen worden bij normale afsluiting teruggegeven.
Een detail dat opgehaald is maar niet naar de database kon worden geschreven,
blijft meetellen. Bij een harde crash zonder eindcheckpoint kan de reservering
conservatief blijven staan. Een budgetstop wijzigt geen voortgangsbestand meer.

De eerdere reserveringen worden uitsluitend gecorrigeerd met artifactbewijs
van alle productieruns van die shop op deze datum. De oorspronkelijke daglimiet
wordt niet verhoogd, verwerkte producten worden niet opnieuw geselecteerd en
het herstel wordt met bronrun-ID's in de checkpoint geaudit. FiftiesStore heeft
100 echte details gestart; daarvoor is geen ongebruikt budget vrij te geven.

Validatie: **88 tests geslaagd**, inclusief negen echte Postgres-tests,
begrensde conflict-retries, bescherming tegen overschrijven van een gelijktijdig
gewijzigd shopbestand, reserveringen bij een lege batch en behoud van een
verbruikte plaats na databasefalen. Actionlint en Python-compilatie slagen.

### Uitkomst eerste extra starts en gecontroleerde hervatting

De acht geslaagde productieruns verwerkten samen **800 details en 710 geldige
EAN's**, zonder technische fouten:

| Shop | Geldige EAN / details | Bewijs |
| --- | --- | --- |
| Shop3345 | 100 / 100 | [39106431657](https://github.com/Vinylofy/curedplant./actions/runs/39106431657) |
| Sounds | 98 / 100 | [39106434877](https://github.com/Vinylofy/curedplant./actions/runs/39106434877) |
| Suburban | 98 / 100 | [39106438019](https://github.com/Vinylofy/curedplant./actions/runs/39106438019) |
| Topnotch | 100 / 100 | [39106439325](https://github.com/Vinylofy/curedplant./actions/runs/39106439325) |
| Variaworld | 88 / 100 | [39106441042](https://github.com/Vinylofy/curedplant./actions/runs/39106441042) |
| Vinyleers | 92 / 100 | [39106442282](https://github.com/Vinylofy/curedplant./actions/runs/39106442282) |
| Vinylfreaks | 36 / 100 | [39106444078](https://github.com/Vinylofy/curedplant./actions/runs/39106444078) |
| Viprecords | 98 / 100 | [39106445717](https://github.com/Vinylofy/curedplant./actions/runs/39106445717) |

Na verificatie van alle productie-artifacts per betrokken shop zijn uitsluitend
**534 ongebruikte reserveringen** teruggegeven. De correctie is onafhankelijk
teruggelezen uit GitHub en per checkpoint geaudit onder
`reservation_recovery_20261018`, inclusief bronrun-ID's en werkelijk gestarte
details. Hierbij telt ook het iMusic-detail mee dat werd opgehaald maar door de
databasefout nog niet kon worden opgeslagen. Er is geen verbruikt record vrijgegeven.

Daarna zijn op de geteste code `89fedac` om **09:20 Nederlandse tijd** de
volgende vervolgruns gestart. Deze vullen alleen het ongebruikte deel van het
dagmaximum; ze verhogen de limiet niet.

| Shop | Eerder gestarte details | Resterend maximum deze run | Vervolgrun |
| --- | --- | --- | --- |
| Bob's Vinyl | 45 | 55 | [39107291696](https://github.com/Vinylofy/curedplant./actions/runs/39107291696) |
| Cdhal | 44 | 56 | [39107293642](https://github.com/Vinylofy/curedplant./actions/runs/39107293642) |
| Everything Jazz | 0 | 100 | [39107295544](https://github.com/Vinylofy/curedplant./actions/runs/39107295544) |
| iMusic | 6 | 94 | [39107297162](https://github.com/Vinylofy/curedplant./actions/runs/39107297162) |
| Recordsonvinyl | 67 | 33 | [39107298921](https://github.com/Vinylofy/curedplant./actions/runs/39107298921) |
| Rockinoutrecords | 0 | 100 | [39107300680](https://github.com/Vinylofy/curedplant./actions/runs/39107300680) |
| Sounds Haarlem | 4 | 96 | [39107302513](https://github.com/Vinylofy/curedplant./actions/runs/39107302513) |

De eerste vervolgrun is inhoudelijk afgerond: Records on Vinyl
[33 geldige EAN's uit 33 details](https://github.com/Vinylofy/curedplant./actions/runs/39107298921),
geen technische fouten. De dagteller staat daarmee op 100.
Everything Jazz [39107295544](https://github.com/Vinylofy/curedplant./actions/runs/39107295544)
heeft het cataloguseinde bereikt zonder onbehandelde nieuwe producten; uitkomst
`waiting`, nul details, dagreservering terug naar nul. Dat telt niet als een
inhoudelijk geslaagde datarun. De overige vervolgruns waren bij deze controle
nog actief; de runlinks tonen de verdere uitkomst.

FiftiesStore had al 100 echte details gestart en krijgt daarom geen extra
productierun boven die daglimiet. De voorbereid herstelde EAN-controle van de
98 eerdere missers blijft beschikbaar voor het volgende dagbudget. De gewone
dagelijkse planning blijft actief. De twee geblokkeerde shops blijven buiten
het extra-startverzoek.

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
  gereserveerde plaatsen komen bij normale afsluiting weer beschikbaar; ieder
  gestart productdetail blijft meetellen, ook bij een databasefout. Bij een harde
  crash kan de reservering conservatief blijven staan. De volgende Amsterdamse
  kalenderdag begint een nieuw budget.
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

## Volledige actuele audit — 18 oktober 2026, 18:33 UTC

Deze meting vervangt bovenstaande historische kleurentellingen. Alle 57 shopworkflows
zijn via de laatste maximaal drie runs en de opgeslagen runlogs gecontroleerd.
Groen = automatische write-run met echte resultaten; oranje = handmatig bewezen
of wachtend op echte automatische resultaten; rood = onopgeloste blokkade.
Een budgetstop of nulresultaat is geen nieuwe bronfout, maar bewijst ook geen automatische dataverwerking.
Prijswrites zijn na commit teruggelezen; getallen hieronder zijn DB-rijen, niet alle gevonden bronproducten.

EAN: {'Oranje': 17, 'Groen': 10, 'Rood': 2}. Prijs: {'Oranje': 26, 'Rood': 2}; 3345 heeft geen prijsworkflow.

| Shop | EAN/detail | Prijs |
| --- | --- | --- |
| 3345 | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106431657) — 100/100 EAN; write; laatste run budgetstop | — geen workflow |
| At The Movies | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39097981243) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108901216) — 801 DB-gecontroleerd |
| Best Kept Records | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39098136897) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109297452) — 4,678 DB-gecontroleerd |
| Black Vinyl | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39098994515) — 89/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108675172) — 182 DB-gecontroleerd |
| Bob’s Vinyl | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107291696) — 29/55 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109091812) — 4,047 DB-gecontroleerd |
| CDHal Ruinen | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107293642) — 45/56 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109297290) — 2,148 DB-gecontroleerd; cron write ontbreekt |
| Coloured Vinyl | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39099793727) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108674956) — 943 DB-gecontroleerd; cron write ontbreekt |
| DGM Outlet | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39100446034) — 1/1 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109297351) — 743 DB-gecontroleerd; cron write ontbreekt |
| Everything Jazz | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107295544) — 0 nieuwe details | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108675352) — 1,299 DB-gecontroleerd |
| FiftiesStore | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39105637387) — 19/25 EAN; read-only; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109094961) — 222 DB-gecontroleerd |
| Get Back Music | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39102576354) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108676808) — 4,485 DB-gecontroleerd; cron write ontbreekt |
| iMusic | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107297162) — 66/66 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39111913834) — 2,769 DB-gecontroleerd; cron write ontbreekt |
| JPC | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39104215856) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39146564774) — 14,848 DB-gecontroleerd |
| Music On Vinyl | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39152893138) — 25/25 EAN; read-only; geen cron | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108676893) — 852 DB-gecontroleerd |
| My Record Store | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39104631185) — 100/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108677067) — 32 DB-gecontroleerd |
| North End Haarlem | [Rood](https://github.com/Vinylofy/curedplant./actions/runs/39066854696) — geblokkeerd; geen cron | [Rood](https://github.com/Vinylofy/curedplant./actions/runs/39108339265) — geblokkeerd; geen cron |
| Platenzaak | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39104705803) — 5/5 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108676960) — 3,571 DB-gecontroleerd |
| Platomania | [Groen](https://github.com/Vinylofy/curedplant./actions/runs/39105403655) — 98/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108678248) — 5,551 DB-gecontroleerd |
| Records on Vinyl | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107298921) — 33/33 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39110734445) — 8,637 DB-gecontroleerd |
| Rockin’ Out Records | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107300680) — 98/100 EAN; write | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108678475) — 114 DB-gecontroleerd; cron write ontbreekt |
| Sounds Delft | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106434877) — 98/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109711911) — 1,950 DB-gecontroleerd |
| Sounds Haarlem | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39107302513) — 96/96 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39112730348) — 1,394 DB-gecontroleerd |
| Sounds Venlo | [Rood](https://github.com/Vinylofy/curedplant./actions/runs/39066857022) — geblokkeerd; geen cron | [Rood](https://github.com/Vinylofy/curedplant./actions/runs/39108343561) — geblokkeerd; geen cron |
| Suburban | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106438019) — 98/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39109093465) — 2,133 DB-gecontroleerd; cron write ontbreekt |
| Top Notch | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106439325) — 100/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108678776) — 299 DB-gecontroleerd; cron write ontbreekt |
| Variaworld | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106441042) — 88/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39111916753) — 4,468 DB-gecontroleerd |
| Vinyl Freaks | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106444078) — 36/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108679668) — 227 DB-gecontroleerd; cron write ontbreekt |
| Vinyleers | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106442282) — 92/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108678694) — 654 DB-gecontroleerd; cron write ontbreekt |
| VIP Records | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39106445717) — 98/100 EAN; write; laatste run budgetstop | [Oranje](https://github.com/Vinylofy/curedplant./actions/runs/39108903024) — 2,610 DB-gecontroleerd; cron write ontbreekt |

**Planningsprobleem:** bij deze 11 prijsworkflows is de cron aanwezig maar `write`
komt alleen uit `inputs.write`, dat bij cron ontbreekt: CDHal Ruinen, Coloured Vinyl, DGM Outlet, Get Back Music, iMusic, Rockin’ Out Records, Suburban, Top Notch, Vinyl Freaks, Vinyleers, VIP Records.
Dit is in deze statusopdracht vastgesteld, nog niet gerepareerd.

JPC is wel correct omgezet: `17 3 * * *`, automatische `write=true`,
geverifieerde write-run 39146564774. Windows listing/prijscron verwijderd
in Vinylofy commit `e30eca6`; handmatige backup en afzonderlijke detailinstellingen behouden.
Curedplant-planningscommit: `0b743fd`. Actionlint en diff checks geslaagd.
Geen extra scraperstarts of databasewrites tijdens deze audit.
