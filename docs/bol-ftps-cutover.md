# Goedgekeurde NL-bronwissel — 8 november 2026

Status: **geslaagd — FTPS PRODUCTIEGEREED: JA (NL, binnen expliciet geaccepteerde dekking).**

## Gemeten productie-uitkomst

- Volledige bron: 916.327 regels, MDTM 8 november 2026, 09:03:23 CET.
- 146.130 geschikte NEW NL-vinylaanbiedingen na 99 veilige quarantaines.
- 86.577 nieuwe neutrale producten; 59.553 bestaande producten gekoppeld.
- 146.130 shopprijzen geschreven en binnen én na commit geverifieerd.
- 585 geslaagde batches; nul writer-fouten; 1.958,891 seconden (32 min 39 s).
- Productieherhaling: ongewijzigde bron in 0,5 seconde overgeslagen, nul
  bulkdownloads en nul databasewrites. De volledige checkpoint werkt.
- Alle twintig bestaande steekproefproducten behielden metadata en covers;
  hun twintig prijzen bleven bij herhaling identiek.
- Website gecontroleerd: nieuw NL-aanbod €26,19 met correcte NL-bestemming,
  bestaande Flogging Molly-prijs €28,89, geen NL-aanbod in BE, geen koopaanbod
  voor een actuele uitverkochte bronrij; homepage en productpagina's HTTP 200.

[Volledige publicatie](https://github.com/Vinylofy/curedplant./actions/runs/42462119932)
— [productieherhaling](https://github.com/Vinylofy/curedplant./actions/runs/42464577676)
— [blijvende evidence](bol-ftps-cutover-evidence.json).

De laatste preflight telde 1.677 huidige API-geschikte aanbiedingen buiten de
veilige FTPS-selectie. Dit verschil is expliciet geaccepteerd; die prijzen zijn
bewaard en kunnen verouderen. Er wordt geen volledige API-dekking of preorder-
semantiek geclaimd. BE is niet gevalideerd voor publicatie en blijft uitgeschakeld.

De twee-uurs-liveplanning is actief. Dezelfde dispatcher heeft de volledige
publicatie en de succesvolle checkpoint-herhaling gestart. Een natuurlijke
GitHub-crontrigger is eerder bewezen in shadowmodus; de eerste volgende natuurlijke
live-cron is op het moment van dit rapport nog niet waargenomen. GitHub bepaalt
het daadwerkelijke startmoment. De losse API-cron is na succesvolle validatie
verwijderd; de automatische API-configuratie blijft `enabled=false`.

Enkele aanvullende publieke REST-tellingen bereikten tijdens de bulkbelasting de
korte leestimeout. Die zware monitoring is vervangen door lichte steekproeven.
Dit waren geen writer-fouten; de writer valideerde alle 146.130 commits en de
gecontroleerde websitepagina's werkten. Er zijn geen shops of frontendbestanden
gewijzigd en geen bestaande canonieke metadata of covers bijgewerkt.

## Goedgekeurde scope en uitvoering

De gebruiker heeft expliciet akkoord gegeven op volledige automatische NL-FTPS-
publicatie en het daarna stoppen van de automatische Marketing API-prijsketen,
met behoud van terugval. Volledige dekking van eerdere API-aanbiedingen is daarbij
uitdrukkelijk geen acceptatievoorwaarde meer. Ontbrekende aanbiedingen blijven
bewaard en kunnen verouderen; zij worden niet automatisch verwijderd of gedeactiveerd.

Om conflicterende writes te vermijden, is de API-keten direct vóór de eerste
volledige FTPS-publicatie gepauzeerd en zijn bestaande runs afgewacht. De API-
broncode, credentials, cursor, historie en overige API-functionaliteit blijven
behouden. Geen BE-publicatie. De strikte NEW/vinyl-, EAN-, identiteit-, bronleeftijd-
en masterdatacontroles blijven gelden. Identiteitsconflicten blijven in quarantaine.

De enige twee-uurscron staat in `bol-feed-shadow.yml` (bestaande workflow-ID), die
nu op basis van de versiebeheerpolicy shadow of live dispatcht. Live gebruikt de
bestaande gecontroleerde `full_write`-workflow op de gewhiteliste Windows-runner.
De losse importcron is verwijderd om dubbel geplande imports te voorkomen.
De zichtbare policy vervangt de eerdere extra, ontoegankelijke repositoryvariabelen;
publicatie vereist nog steeds main, expliciete goedkeuring, live-policy, API-pauze
en geen onafgeronde API-runs. De CLI accepteert het dekkingsverschil alleen met
het expliciete NL-akkoord `user_2026-11-08`, en rapporteert de geaccepteerde aantallen.

Verificatie vóór activatie: 114 bol-tests geslaagd, inclusief 23 PostgreSQL-tests;
actionlint op de drie FTPS-workflows en de behouden handmatige API-workflow geslaagd. Een eerdere natuurlijke cronrun
42434250292 en bijbehorende volledige Windows-review 42434257698 zijn geslaagd.

## Terugval

1. Zet `enabled=false` in `config/bol-feed-automation.json` en commit op main.
2. Laat een lopende FTPS-writer afronden; controleer de laatste write-evidence.
   Annuleer alleen als een gecontroleerde onderbreking noodzakelijk is; reeds
   gecommitteerde batches blijven bewaard en de volledige checkpoint schuift niet op.
3. Zet `enabled=true` in `config/bol-price-cycle.json` en herstel desgewenst de
   voormalige `0,30 * * * *`-cron in `price-bol-api.yml`; commit op main.
   De handmatige workflow met gecontroleerde voortzetting blijft beschikbaar.
4. Onderzoek een eventueel eerder API-circuit-breakerprobleem vóór expliciet
   hervatten. De bestaande API-workflow/code en alle credentials blijven beschikbaar.

Geen destructieve terugdraaiing van producten, prijzen of historie. De API-writer
behoudt zijn bescherming tegen oudere prijzen. Hervat nooit beide automatische
writers tegelijk.
