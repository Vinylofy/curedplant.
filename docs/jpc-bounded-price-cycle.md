# JPC: hervatbare dagelijkse prijsronde

`Curedplant | Price | Jpc` gebruikt `price-jpc.yml`, Ubuntu, één prijsworker tegelijk. De bestaande EAN-workflow blijft zelfstandig lopen. De oude vijf uur durende prijsjob wordt vervangen; de bronparser en de bestaande databasewriter blijven in gebruik.

## Ritme en grenzen

- Eén nieuwe dagelijkse ronde vanaf 03:17 UTC (04:17 Nederlandse wintertijd / 05:17 zomertijd).
- Maximaal 50 pagina's per automatische run. Na een succesvol deel start de workflow zelf het volgende deel. Een afgeronde ronde stopt tot de volgende dag; dit is geen oneindige nieuwe crawl.
- Een cron om minuut 17 van ieder uur herneemt onderbroken cycli. GitHub kan cronstarts vertragen; het is geen exacte klokgarantie.
- Eén bronproces, vier seconden tussen pagina's. 502/503/504 en verbindingsfouten: maximaal twee herpogingen, met 60 en 120 seconden pauze. 401/403/429 worden niet opnieuw geprobeerd.
- Een worker verzamelt circa tien minuten, met maximaal vijf minuten voor een lopende bronaanvraag. De Actions-job stopt uiterlijk na 25 minuten, met ruimte voor rapportage.
- Bij bronfalen worden eerdere complete pagina's nog gecontroleerd en gepubliceerd. De mislukte pagina wordt niet overgeslagen. De volgende poging wacht minimaal 30 minuten; na drie opeenvolgende fouten op hetzelfde hervatpunt wordt dat zes uur.

## Opslag en bewijs

Iedere afgeronde pagina krijgt een lokaal atomair, geflusht journal. Na maximaal tien pagina's controleert de worker de prijzen en werkt hij bestaande aanbiedingen bij, inclusief de bestaande controle vóór en na commit. Pas daarna wordt de cursor duurzaam opgeslagen op branch `jpc-price-progress`, bestand `state/jpc-price/checkpoint.json`. Deze branch bewaart alleen route-snapshot, cursor, paginahashes, totaaltellingen en foutstatus; geen grote productcatalogus en geen credentials.

Bij een harde machinecrash of publicatiefout worden maximaal tien pagina's opnieuw gelezen. Een crash na databasecommit maar vóór checkpoint veroorzaakt een veilige herhaling: de bron wordt opnieuw gelezen, nieuwere databasegegevens worden beschermd en onveranderde prijzen maken geen dubbele wijzigingshistorie. De worker claimt geen exacte transactionele atomiciteit tussen PostgreSQL en GitHub.

Artifacts `jpc-bounded-prices-<run-id>` bevatten `summary.json`, lokale `progress.json` en de pagina-journals. Bewaartermijn: drie dagen. Per run zijn bronpagina's, geldige prijzen, databaseupdates, geverifieerde updates en de resterende cursor zichtbaar in de Actions-summary. De totaaltellingen tellen waarnemingen per deel; hetzelfde product kan in meerdere categorieën voorkomen. Dit is geen unieke catalogustelling.

Een deel zonder bestaande prijsmatches mag de cursor wel voortzetten, maar heet `checked_no_price_updates`, niet bewezen prijssucces. Een prijsvalidatiefout of databasefout verplaatst de cursor niet. De worker maakt geen producten of aanbiedingen aan en wijzigt geen EAN's of covers. Weggevallen producten krijgen geen verzonnen timestamp en worden niet op basis van een deelrun gedeactiveerd.

## Handmatig testen en pauzeren

`limit` is nu het maximum aantal pagina's in deze run (1–100; standaard 50), geen onbeperkte volledige scan. `write=false` controleert de eerstvolgende pagina's zonder databasewrites of wijzigingen aan de gedeelde cursor. `write=true` publiceert gecontroleerde delen en bewaart het hervatpunt. `continue_cycle=false` laat een handmatige proef na dit deel stoppen.

Automatisering wordt bestuurd door `config/jpc-price-cycle.json`. Tijdens ingebruikname staat `enabled=false`; geplande/doorlopende runs halen dan niets op. Na een gecontroleerde dry-run en write-proef wordt dit op `true` gezet. Voor pauzeren: zet het terug op `false` of disable de JPC-prijsworkflow in Actions. EAN blijft onafhankelijk.

Voor een volledige ronde van circa 5.000 pagina's is een voorlopige raming 10–14 uur inclusief verzoeken, wachttijden en het starten van deeljobs. Veel bronfouten kunnen dit verlengen. Gecontroleerde prijzen verschijnen al na elk gepubliceerd deel; de eerste echte cyclus moet de doorlooptijd bevestigen.
