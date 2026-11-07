# bol.com FTPS-migratie — implementatierapport

Datum: 7 november 2026. **FTPS PRODUCTIEGEREED: NEE.**

De bestaande importer is uitgebreid en de live bron is gecontroleerd. Er zijn
geen productiewrites uitgevoerd, geen shops aangemaakt en geen frontendbestanden
gewijzigd. De Marketing API blijft actief. Het voorstel staat op branch
`codex/bol-ftps-migration`; productiepublicatie is niet uitgevoerd.

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

## 8. Resterende blokkades en pilotvoorstel

- Expliciete goedkeuring voor publieke fase D ontbreekt. Voorstel: maximaal
  twintig NL-producten in de bestaande bol-shop; het geobserveerde snapshot telt
  acht bestaande en twaalf nieuwe producten. De pilot is gebonden aan de
  beoordeelde SHA-256. Een gewijzigd snapshot wordt vóór databasewrites geweigerd
  en vereist nieuwe review.
- Formaatconflicten vereisen veilige afhandeling vóór een volledige publicatie;
  de huidige writer blokkeert ze zonder productiegegevens te overschrijven.
- Bestaande aanboddekking en eventuele verschillen moeten vóór API-uitfasering
  worden beoordeeld en opgelost.
- API-preorderfunctionaliteit is nog niet aantoonbaar equivalent; de FTPS-reader
  claimt bij een toekomstige release daarom geen actuele voorraad.
- Productieschrijftijd, volledige transactieduur en automatisch geplande werking
  zijn nog niet bewezen. Een read-only scan bewijst die eigenschappen niet.
- Supabase/frontend-controle na publicatie en echte affiliate-attributie ontbreken.
  Verzendkosten/sellerinformatie staan alleen in bestaande raw evidence; er is
  geen nieuwe per-offer frontendopslag of UI toegevoegd.
- BE-productie blijft geblokkeerd tot een eigen shop/marktzichtbaarheid afzonderlijk
  is gevalideerd. Geen BE-shop is aangemaakt.

## 9. Tests, commits en workflowlinks

84 gerichte bol-tests slagen, inclusief 11 integratietests met een geïsoleerde,
tijdelijke PostgreSQL-database. Die tests schrijven niet naar Supabase.
Actionlint slaagt voor beide FTPS-workflows; `git diff --check` slaagt.

Belangrijkste commits op de voorgestelde branch: `4440290`, `c2a3f65`, `c7acedd`,
`87f4f11`, `b9c3790`, `d533468`, `6fb64c1`. Zie ook [alle migratiewijzigingen](https://github.com/Vinylofy/curedplant./compare/main...codex/bol-ftps-migration).

- [Oorspronkelijke live schema-inspectie](https://github.com/Vinylofy/curedplant./actions/runs/42352414844)
- [Volledige schema-inspectie](https://github.com/Vinylofy/curedplant./actions/runs/42362647191)
- [NL dry-run en volledige databasevergelijking](https://github.com/Vinylofy/curedplant./actions/runs/42363138872)
- [Afzonderlijke marktstatistieken en aanboddekking](https://github.com/Vinylofy/curedplant./actions/runs/42363509733)
- [Gedetailleerde blijvende evidence](bol-ftps-validation-evidence.json)
- [Bediening, voorwaarden en herstel](bol-affiliate-import.md)

## 10. Conclusie

**FTPS PRODUCTIEGEREED: NEE.** Live toegang, schema, selectie en read-only
prijs/EAN-validatie zijn bewezen. De vereiste goedgekeurde productiepilot,
volledige conflict/dekkingsafhandeling, functionele API-pariteit en zelfstandig
gevalideerde productieplanning ontbreken nog. De Marketing API blijft actief.
