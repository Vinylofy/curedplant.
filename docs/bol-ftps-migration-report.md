# bol.com FTPS-migratie — implementatierapport

Datum: 7 november 2026. **FTPS PRODUCTIEGEREED: NEE.**

De expliciet goedgekeurde NL-productiepilot is geslaagd: twintig aanbiedingen
zijn gepubliceerd, inclusief twaalf nieuwe producten. De acht bestaande producten
behielden hun canonieke metadata en covers. De productieherhaling schreef niets
opnieuw. Supabase en de publieke frontend zijn gecontroleerd.

De code staat op `main`. Er zijn geen shops aangemaakt en geen frontendbestanden
gewijzigd. De Marketing API blijft actief; de volledige automatische FTPS-bronwissel
is nog niet vrijgegeven. De oorspronkelijke read-only resultaten staan hieronder,
gevolgd door het actuele pilotresultaat in §5a.

## Actuele voortzetting: knelpunten onderzocht en technisch afgevangen

De latere volledige Windows-validatie heeft een nieuw snapshot van 913.984 regels
geverifieerd (MDTM 7 november 2026, 21:03:54 CET). Daaruit blijven 146.011 geldige
nieuwe NL-vinylaanbiedingen over na veilige quarantaine van 100 identiteits- en
formaatconflicten. Er zijn geen canonieke formaten gecorrigeerd of overschreven.
94 conflicten raken producten met `metadata_source=musicbrainz`; uitsluiting
beschermt die bestaande data. De historische 99-conflictentelling hieronder is
vervangen door deze nieuwe momentopname.

De actuele read-only vergelijking telt 52.938 actieve bol-shopaanbiedingen, waarvan
49.944 in de geschikte bronselectie voorkomen. Van 2.994 ontbrekende aanbiedingen
zijn er 1.598 op het meetmoment zichtbaar en volgens de bestaande API-regels
API-geschikt. Bronverklaring: 2.378 EANs ontbreken in Entertainment, 553 vallen af
op drager, 36 hebben geen NL-aanbieding, 26 zijn niet NEW; één geval is niet
verklaard door het eerder vastgelegde broncohort terwijl de API doorliep.
Twintig van twintig onderzochte ontbrekende EANs hebben nog een geldig actueel
NEW API-aanbod. Acht daarvan zijn door bol als Boek geclassificeerd en één als
platenspeleronderdeel; dit verklaart voor die voorbeelden een andere feedgroep,
maar bewijst niet de fysieke drager. Eén gecontroleerd geval heeft hetzelfde
bol-product-ID bij verschillende EANs: er is geen onveilige aliasmatch toegepast.

Opgeloste technische knelpunten:

- De Windows-runner heeft opnieuw IP-controle, volledige download, integriteits-
  en catalogusvalidatie en aanvullende metadata-inspectie succesvol uitgevoerd.
- Identiteitsconflicten worden vóór publicatie uit alle markten van het plan
  verwijderd en met redenen gerapporteerd; zij blokkeren niet langer de veilige
  restselectie en veranderen geen masterdata.
- Volledige writes gebruiken maximaal 250 producten per atomaire batch, bestaande
  product-/prijs-/historiecontracten met pipelining, vaste GTIN-/shopidentiteit,
  oudere-prijsbescherming en verificatie binnen én na elke commit. Eerdere
  gecommitteerde batches worden bij een latere fout als voortgang bewaard; alleen
  volledig succes krijgt een checkpoint. Dit is geen onbewezen globale transactie.
- De gedeelde bol-lock wordt bij bulkwerk niet onbeperkt afgewacht: bezet betekent
  geen mutatie en een begrensde retry. Fouten krijgen een veilige fasenaam.
- Volledige publicatie is expliciet geblokkeerd bij onopgeloste dekking van huidige
  zichtbare API-geschikte aanbiedingen. Oude/ongeschikte rijen blijven bewaard.
- Twee-uurlijkse **read-only shadow** is geconfigureerd via
  `config/bol-feed-automation.json` en de bestaande reviewworkflow. Een afzonderlijk
  mode- en codegebonden review-checkpoint voorkomt nieuwe bulkdownloads van
  ongewijzigde bronnen en kan nooit een schrijverscheckpoint vervangen.
- Volledige publicatie staat bovendien expliciet op slot zolang de versiebeheer-
  policy `mode=shadow`, `publication_allowed=false` is.

Validatie van deze voortzetting: 109 bol-tests, inclusief 22 tijdelijke
PostgreSQL-integratietests, en 43 prijscontracttests (de zeven daarin optionele
PostgreSQL-tests zijn ook afzonderlijk op de eigen tijdelijke server uitgevoerd).
Actionlint slaagt voor de drie FTPS-workflows. De tijdelijke prestatietest verwerkt
200 producten/400 marktprijzen met minder dan dertig expliciete cursorrequests;
dit bewijst de weggenomen per-aanbieding-roundtrips, niet de productieschrijftijd
van een complete catalogus met alle gedeployde triggers.

Deze voortzetting heeft geen nieuwe product- of prijswrites in Supabase gedaan.
De bestaande API-keten blijft actief. De automatische publicatie is niet aangezet;
shadow is uitsluitend bron-/databasecontrole zonder schrijfpad. Een volledige
FTPS-only bronwissel blijft niet veilig bewezen. De aanvullende bronbestanden
zijn bewust alleen met metadata en begrensde headerprobes onderzocht: onder meer
International Books is 4,78 GB gecomprimeerd, boven de bestaande downloadlimiet.
Een gedeelde CSV-header bewijst geen vinylrecord; boeken/accessoires en
prijs-overname over verschillende EANs zijn niet geïmporteerd.

Blijvende actuele evidence:

- [Volledige nieuwe bronvalidatie](https://github.com/Vinylofy/curedplant./actions/runs/42412781246)
- [Live API-/GPC-vergelijking](https://github.com/Vinylofy/curedplant./actions/runs/42414643425)
- [Begrensde header-/grootteprobes](https://github.com/Vinylofy/curedplant./actions/runs/42415218461)
- [Actuele bron- en conflictevidence](bol-ftps-source-evidence.json)
- [Voorbereide bronvragen en reproduceerbare gevallen](bol-feed-source-investigation.md)

### Automatische schaduwketen daadwerkelijk gecontroleerd

[PR #7](https://github.com/Vinylofy/curedplant./pull/7) is samengevoegd. De
versiebeheerpolicy staat op `enabled=true`, `mode=shadow`,
`publication_allowed=false`. De twee-uursplanning gebruikt dezelfde dispatchketen
als de geslaagde end-to-end test; volledige productiepublicatie staat niet aan.

Een eerste integratierun stopte vóór mutatie door een CLI-specifieke fout in de
nieuwe vereiste-dekkingscontrole. Die fout is hersteld in `46e3d06` en met een echte
`python -m` subprocess-test tegen tijdelijke PostgreSQL afgedekt. De daarna
uitgevoerde main-keten is geslaagd:

- [Dispatcher](https://github.com/Vinylofy/curedplant./actions/runs/42416357145)
  startte zelfstandig de bestaande Windows-review.
- [Volledige review](https://github.com/Vinylofy/curedplant./actions/runs/42416364339)
  verwerkte 913.984 regels, vond 146.011 geschikte aanbiedingen, sloot 100 conflicten
  uit en schreef nul productiegegevens. Importerduur: 199,515 seconden.
- De actuele dekkingsmomentopname telt 52.941 actieve shopaanbiedingen, 49.946
  gedekt en 2.995 buiten de selectie. Binnen de 51.139 huidige zichtbare
  API-geschikte aanbiedingen ontbreken er 1.600. De API blijft intussen doorwerken;
  dit verklaart kleine verschillen met de eerder vastgelegde auditcohorten.
- [Tweede dispatcher](https://github.com/Vinylofy/curedplant./actions/runs/42416771485)
  en [review](https://github.com/Vinylofy/curedplant./actions/runs/42416778715)
  bevestigden de onveranderde bron via het afzonderlijke review-checkpoint:
  `status=unchanged_feed`, nul writes, geen bulkdownload, 0,406 seconde importertijd.
- Het vorige volledige reviewmoment en de exacte bron-SHA-256 staan in de
  skip-evidence. Een schaduwcheckpoint kan geen schrijverscheckpoint autoriseren.

De eerste natuurlijke cron-trigger is op dit rapportmoment nog toekomstig;
handmatige start van dezelfde automatische dispatchketen is wél end-to-end
bewezen. De volledige productiebronwissel is niet geactiveerd of goedgekeurd als
voltooid. Bestaande API-credentials, broncode, cursors en historie zijn behouden.

Zie [de blijvende shadow-, checkpoint- en probe-evidence](bol-ftps-shadow-evidence.json).

De onderstaande eerdere resultaten blijven als historische pilot- en
implementatie-evidence bewaard. De actuele blokkades en tellingen staan hierboven.

## 1. Connectiviteit en download

De bestaande zelf gehoste Windows-runner is gebruikt, met controle van het
gewhiteliste publieke IPv4 vóór credentialgebruik. Authenticatie, explicit FTPS,
passive mode, beveiligde dataverbinding en download zijn succesvol geobserveerd.

De gevalideerde bron heeft MDTM `2026-11-07T10:01:47+00:00`: 7 november 2026,
11:01:47 CET voor het oorspronkelijke snapshot. MDTM is de bronbestandsdatum,
geen onafhankelijk bewezen generatietijd. Het uiteindelijke snapshot is exact
vastgelegd in de evidence hieronder.

- Gelezen bronregels: 902,918; volledige feed: `True`.
- Compressed bytes: 338,029,424.
- Uncompressed bytes: 1,214,971,950.
- Integriteit: `verified_full_read`.
- SHA-256: `1e5bed487fbc25766d1a57832f24764d960b9c5766f8e7a5f7003da938654971`.
- Laatste validatieduur: 329.625 seconden, exclusief runner-setup.

## 2. Werkelijke feedstructuur

Het schema gebruikt `ean`, `productId`, `title`, `Performer`, `Format`,
`productPageUrlNL` en `productPageUrlBE`. De eerdere speculatieve veldnamen zijn
gecorrigeerd. De aanbiedingen gebruiken per markt `sellingPrice`, `shippingCost`,
`condition`, `isDeliverable`, `releaseDate` en `sellerType`.

Alleen geobserveerde vinylwaarden worden geaccepteerd: `LP`, `7" Vinyl`,
`12" Vinyl`, `10" Vinyl`, `LP + downloadcode`. `new` is de expliciete nieuwstaat;
`used`, CD/DVD, cassette en onvoldoende bewezen dragers vallen af. Gemengde
LP/CD/DVD-bundels blijven uitgesloten. `sellingPrice` is leidend, nooit `listPrice`.

Beschikbaarheid gebruikt werkelijk `Y`/`N`, niet de eerdere true/false-aanname.
Bij `Y` leidt een toekomstige of onleesbare releasedatum conservatief tot `unknown`;
`Y` bij een preorder bewijst geen huidige voorraad. Deze aanvullende bescherming
is na de volledige scan getest met de twintig bewaarde echte bronrecords:
19 maal `in_stock`, eenmaal `out_of_stock` per markt. Het toekomstige
voorbeeld heeft bronwaarde `N`; toekomstig `Y` en onleesbare datums zijn met
regressietests gecontroleerd. Expliciet `N` blijft `out_of_stock`. De volledige scan liep op commit
`b9c3790`; de releasedatumcorrecties staan in `d533468` en `6fb64c1`.
Deze aanvullende bescherming is met echte samples en regressietests gecontroleerd. De prijs-, EAN- en dekkingsaantallen
worden door die beschikbaarheidscorrectie niet veranderd.

`config/bol-feed.live.json` heeft uitsluitend NL als geverifieerde publicatiemarkt.
Het voorbeeldprofiel blijft `live_schema_verified=false`. BE heeft afzonderlijke
bronstatistieken, maar nog geen gevalideerde eigen productie-shop en publicatie.
Er worden geen bol-afbeeldingen of beschrijvingen overgenomen; artiest/titel
worden niet over canonieke MusicBrainz-data geschreven.

## 3. Dry-run van twintig echte NL-producten

De eerste volledige NL-validatie vond:

| Maatstaf | Aantal |
| --- | ---: |
| Gelezen regels | 20 |
| Geldige nieuwe vinylproducten | 20 |
| Bestaande EAN-matches | 8 |
| Nieuwe producten, alleen gepland | 12 |
| Geldige prijzen | 20 |
| Afgewezen records | 0 |
| Productiewrites | 0 |

Van acht bestaande matches hadden vier dezelfde prijs, drie een andere prijs en
een nog geen bol-shopaanbieding. Affiliate links zijn gecontroleerd op host,
markt, product-ID en gecodeerde Site_ID. Werkelijke kliktoerekening in het
bol-account is niet getest.

## 4. Volledige catalogusvalidatie en afzonderlijke markten

De laatste volledige scan gebruikte één download voor NL en BE, met aparte
marktaantallen en uitsluitend read-only databasevergelijkingen:

| Markt | Geldige nieuwe vinylproducten | Prijzen | Bestaande matches | Nieuwe producten, gepland |
| --- | ---: | ---: | ---: | ---: |
| NL | 144,422 | 144,422 | 59,370 | 84,953 |
| BE | 135,810 | 135,810 | 56,754 | 78,961 |

De eerdere NL-only scan selecteerde 144.422 aanbiedingen: 59.370 bestaande
matches, 84.953 nieuwe productkandidaten en 99 formaatconflicten. Afwijzingen:
747.968 niet bewezen vinyl, 364 ongeldige barcodes, 7.626 niet nieuw, 2.535 zonder
NL-aanbieding en 3 ongeldige bedragen. Er werden 30.863 ongewijzigde prijzen,
18.833 gewijzigde prijzen en 9.674 nieuwe shopaanbiedingen bij bestaande producten
gevonden. Dit zijn vergeleken prijzen, geen uitgevoerde updates.

Laatste scan: 99 database-identiteits/formaatconflicten. De bestaande
gecontroleerde writer weigert een publicatie met zulke conflicten; hij corrigeert
de canonieke productformaten niet automatisch. De volledige conflictlijst en
alle afwijzingsredenen staan in [de evidence](bol-ftps-validation-evidence.json).

Dekking van bestaande actieve bol-shopaanbiedingen op het moment van de laatste
read-only snapshot:

```json
{
  "NL": {
    "existing_active_shop_offers": 52718,
    "covered_by_feed": 49696,
    "absent_from_eligible_feed": 3022
  }
}
```

Ontbrekende aanbiedingen worden niet verwijderd of gedeactiveerd. Hun bestaande
frontend-freshnessvoorwaarden blijven gelden; ontbrekende dekking is dus een
blokkade voor een ongecontroleerde bronwissel, geen reden om producten te wissen.
BE heeft geen eigen gevalideerde shop-ID; zijn prijzen zijn niet ten onrechte
met de NL-shop vergeleken.

## 5. Database- en prijsmatching

De bestaande GTIN-normalisatie, productcreatie, shopkoppelingen, prijstabellen,
prijshistorie en gecontroleerde writer blijven leidend. Nieuwe producten krijgen
neutrale placeholders met metadatareview; bestaande masterdata blijft behouden.

EAN/land resulteert in een vaste combinatie van product en marktshop. NL
hergebruikt de bestaande bol-shop. Oudere bronnen overschrijven geen nieuwere
prijzen. Replays zijn idempotent en ongewijzigde prijzen/beschikbaarheid voegen
ook op een nieuwe kalenderdag geen dubbele historie toe. Conflicterende
bronaanbiedingen worden uitgesloten; productlinks moeten bij bron-ID en land passen.

## 5a. Goedgekeurde productiepilot en herstel

De gebruiker heeft het eerder beschreven voorstel expliciet goedgekeurd met
“ga door”. [PR #5](https://github.com/Vinylofy/curedplant./pull/5) is samengevoegd;
de pilot bleef beperkt tot dezelfde twintig NL-producten en dezelfde feedchecksum.

De eerste poging op de Windows-runner downloadde en valideerde de juiste feed,
maar stopte in de databasefase met `QueryCanceled`. Vergelijking vóór/na toonde
exact dezelfde acht producten en zeven bestaande bol-prijsregels: geen nieuwe
producten of gecommitteerde prijswijzigingen uit die poging. Read-only diagnose
bevestigde bestaande lookup-indexen, een statement-time-out van twee minuten en
geen advisory locks op het meetmoment. De precieze oorzaak/fase van die eerste
time-out is niet bewezen; er is geen productiedatabase-index of time-outinstelling
gewijzigd om de fout te omzeilen.

Vervolgopdrachten kregen geen Windows-runner toegewezen en zijn geannuleerd. De
handmatige pilot is vervolgens hersteld vanuit het onveranderlijke, gevalideerde
selectie-artifact van de oorspronkelijke Windows-poging, via **dezelfde bestaande
writer**. Deze herstelroute vereist `main`, expliciete publicatiegoedkeuring, een
vertrouwde afgeronde main-workflow, de beoordeelde feedchecksum, een geverifieerd
NL-profiel en maximaal twintig unieke geldige barcodes. Markt, affiliate-link,
product-ID, bedragen en bestaande EAN-matches worden opnieuw gecontroleerd. Er is
geen alternatieve bron of parallelle importer toegevoegd. De geplande FTPS-feedjob
blijft de gewhiteliste Windows-runner vereisen.

| Productiecontrole | Resultaat |
| --- | ---: |
| Beoordeelde NL-producten | 20 |
| Bestaande producten, canonieke metadata en covers behouden | 8 |
| Nieuwe producten via de bestaande veilige creatielogica | 12 |
| Geschreven prijs-/shopaanbiedingen | 20 |
| Prijs en link binnen én na commit geverifieerd | 20 |
| Onafhankelijk gelezen prijzen, beschikbaarheid en links correct | 20 |
| Beschikbaarheid: in_stock / out_of_stock | 19 / 1 |
| Historieregels voor dit snapshot na publicatie | 18 |
| Nieuwe producten of prijswrites bij productieherhaling | 0 |
| Historieregels vóór / na die herhaling | 18 / 18 |

De twaalf nieuwe producten hebben neutrale `Vinyl <EAN>`-titels,
`metadata_source=shop_observed`, `metadata_status=placeholder`,
`metadata_needs_review=true`, geen overgenomen bol-cover en geen geïmporteerde
bol-artiest als canonieke metadata. De reguliere verrijking blijft leidend.

De succesvolle herstelrun duurde 23,141 seconden voor matching/writes/verificatie;
de herhaling 13,363 seconden. Deze beperkte pilot is geen benchmark voor een
volledige cataloguspublicatie.

Publieke frontendcontroles met Playwright:

- Een [bestaand product](https://www.vinylofy.com/product/8dcd58b7-a5bd-4157-8d2d-706b7fb61e4e?market=NL)
  toont bol €28,89 en de correcte affiliate-link.
- Een [nieuw product](https://www.vinylofy.com/product/50f8c4a6-de88-42a9-b249-24781f0e10ad?market=NL)
  toont de neutrale placeholder, bol €69,95 en de correcte affiliate-link;
  dezelfde controle slaagde op preview.
- Het [uitverkochte product](https://www.vinylofy.com/product/38ca09e7-0f60-4695-947e-c342f11b79b0?market=NL)
  toont geen bol-koopaanbieding.
- De [BE-weergave van het bestaande product](https://www.vinylofy.com/product/8dcd58b7-a5bd-4157-8d2d-706b7fb61e4e?market=BE)
  toont geen NL-bol-aanbieding. De bestaande bol-shop heeft uitsluitend een
  bevestigde NL-bestemming.

Alle twintig bronaanbiedingen hebben expliciet `shippingCost=0.00`. De gecontroleerde
zichtbare aanbiedingen tonen daarvoor gratis verzending via de bestaande
frontendlogica; dit bewijst geen nieuwe algemene per-offer verzendkostenopslag.
Er zijn geen affiliate-aankooplinks aangeklikt en geen accountattributierapporten
gecontroleerd.

Chromium kende de omgevingsproxy-CA niet. Daarom zijn de Playwright-responses via
een TLS-verifiërende client met de systeem-CA geladen, zonder TLS-verificatie uit
te schakelen. Afbeeldingen/fonts/media en externe verzoeken zijn in deze
browsercontrole geblokkeerd; de pagina-JavaScript en prijs-/linkweergave zijn wel
uitgevoerd. Er zijn geen frontendbestanden gewijzigd.

Zie [de blijvende pilotevidence](bol-ftps-pilot-evidence.json),
[de succesvolle publicatie](https://github.com/Vinylofy/curedplant./actions/runs/42365716216)
en [de productieherhaling](https://github.com/Vinylofy/curedplant./actions/runs/42365907287).

## 6. Automatisering en frequentie

De voorbereide publicatieworkflow ondersteunt read-only, een expliciet goedgekeurde
pilot van maximaal twintig NL-producten en een volledige NL-import. Een
voorgestelde twee-uursplanning (`15 */2 * * *`, UTC) pollt op nieuwe MDTM; alleen
een succesvol volledig verwerkt snapshot mag de volgende download overslaan.
Retries zijn begrensd. Mislukte downloads wijzigen geen bestaande prijzen.

De planning is **niet door deze implementatie geactiveerd**. Zowel
`BOL_FTPS_AUTOMATION_ENABLED=true` als `BOL_FTPS_PRODUCTION_APPROVED=true` zijn
vereist; hun bestaande repositorywaarden konden wegens GitHub HTTP 403 niet
worden uitgelezen. De nieuwe workflow staat op de voorgestelde branch. De
precieze verversingsfase/timezone en volledige schrijftijd zijn nog niet bewezen.

Volledige writes vereisen bovendien een gepauzeerde automatische API-keten en
geen onafgeronde API-workflows. De bestaande API-configuratie is nu ongewijzigd.
Beide writers delen de bestaande database-lock. De FTPS-workflows delen een
concurrencygroep zonder annulering van lopende imports.

## 7. Marketing API en herstel

`.github/workflows/price-bol-api.yml` en `config/bol-price-cycle.json` zijn niet
gewijzigd. De API-keten blijft actief. Credentials, broncode, cursor, overige
API-functionaliteit en prijshistorie blijven behouden. Er is geen gelijktijdige
automatische FTPS-prijsschrijver aangezet.

Herstelprocedure: eerst FTPS-automatisering stoppen en lopende writes laten
afronden, dan na beoordeling de bestaande API-keten expliciet herstellen met de
bestaande resumeprocedure. Geen van beide automatische bronnen wordt hier omgezet.

## 8. Resterende blokkades voor de volledige bronwissel

- De beperkte NL-productiepilot is goedgekeurd en geslaagd. Dit is geen
  goedkeuring voor een volledige cataloguspublicatie of API-uitschakeling.
- Formaatconflicten vereisen veilige afhandeling vóór een volledige publicatie;
  de huidige writer blokkeert ze zonder productiegegevens te overschrijven.
- Bestaande aanboddekking en eventuele verschillen moeten vóór API-uitfasering
  worden beoordeeld en opgelost.
- API-preorderfunctionaliteit is nog niet aantoonbaar equivalent; de FTPS-reader
  claimt bij een toekomstige release daarom geen actuele voorraad.
- Volledige schrijftijd, transactieduur en automatisch geplande werking zijn
  nog niet bewezen. De eerste time-out is niet causaal verklaard en de latere
  Windows-runnerbeschikbaarheid is niet hersteld of structureel bewezen.
- Supabase/frontend-controles voor de pilot zijn geslaagd. Echte
  affiliate-accountattributie is niet gecontroleerd. Verzendkosten/sellerinformatie
  blijven in bestaande raw evidence; er is geen nieuwe per-offer UI/opslag.
- BE-productie blijft geblokkeerd tot een eigen shop/marktzichtbaarheid afzonderlijk
  is gevalideerd. Geen BE-shop is aangemaakt.

## 9. Tests, commits en workflowlinks

88 gerichte bol-tests slagen, inclusief 13 integratietests met een geïsoleerde,
tijdelijke PostgreSQL-database. Die tests schrijven niet naar Supabase.
Actionlint slaagt voor beide FTPS-workflows; `git diff --check` slaagt.

Belangrijkste initiële commits: `4440290`, `c2a3f65`, `c7acedd`,
`87f4f11`, `b9c3790`, `d533468`, `6fb64c1`. Zie ook [alle migratiewijzigingen](https://github.com/Vinylofy/curedplant./compare/main...codex/bol-ftps-migration).

- [Oorspronkelijke live schema-inspectie](https://github.com/Vinylofy/curedplant./actions/runs/42352414844)
- [Volledige schema-inspectie](https://github.com/Vinylofy/curedplant./actions/runs/42362647191)
- [NL dry-run en volledige databasevergelijking](https://github.com/Vinylofy/curedplant./actions/runs/42363138872)
- [Afzonderlijke marktstatistieken en aanboddekking](https://github.com/Vinylofy/curedplant./actions/runs/42363509733)
- [Samengevoegde implementatie — PR #5](https://github.com/Vinylofy/curedplant./pull/5)
- [Samengevoegde diagnose — PR #6](https://github.com/Vinylofy/curedplant./pull/6)
- [Herstel via bestaande writer — cea6c9e](https://github.com/Vinylofy/curedplant./commit/cea6c9e)
- [Geslaagde productiepilot](https://github.com/Vinylofy/curedplant./actions/runs/42365716216)
- [Geslaagde productieherhaling zonder writes](https://github.com/Vinylofy/curedplant./actions/runs/42365907287)
- [Pilotevidence](bol-ftps-pilot-evidence.json)
- [Gedetailleerde blijvende evidence](bol-ftps-validation-evidence.json)
- [Bediening, voorwaarden en herstel](bol-affiliate-import.md)

## 10. Conclusie

**FTPS PRODUCTIEGEREED: NEE.** Live toegang, schema, selectie en read-only
prijs/EAN-validatie én de goedgekeurde beperkte NL-productiepilot zijn bewezen.
Conflicten zijn veilig gequarantaineerd en bulk-/shadowverwerking is technisch
voorbereid. Volledige brondekking, functionele API-pariteit, echte volledige
productieschrijfprestaties en zelfstandig bewezen live planning ontbreken nog.
De Marketing API blijft actief.
