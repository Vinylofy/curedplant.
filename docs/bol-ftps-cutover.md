# Goedgekeurde NL-bronwissel — 8 november 2026

Status: bronwissel in uitvoering; volledige productie-uitkomst nog te verifiëren.

De gebruiker heeft expliciet akkoord gegeven op volledige automatische NL-FTPS-
publicatie en het daarna stoppen van de automatische Marketing API-prijsketen,
met behoud van terugval. Volledige dekking van eerdere API-aanbiedingen is daarbij
uitdrukkelijk geen acceptatievoorwaarde meer. Ontbrekende aanbiedingen blijven
bewaard en kunnen verouderen; zij worden niet automatisch verwijderd of gedeactiveerd.

Om conflicterende writes te vermijden, wordt de API-keten direct vóór de eerste
volledige FTPS-publicatie gepauzeerd en worden bestaande runs afgewacht. De API-
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
actionlint op de drie FTPS-workflows geslaagd. Een eerdere natuurlijke cronrun
42434250292 en bijbehorende volledige Windows-review 42434257698 zijn geslaagd.

## Terugval

1. Zet `enabled=false` in `config/bol-feed-automation.json` en commit op main.
2. Laat een lopende FTPS-writer afronden; controleer de laatste write-evidence.
   Annuleer alleen als een gecontroleerde onderbreking noodzakelijk is; reeds
   gecommitteerde batches blijven bewaard en de volledige checkpoint schuift niet op.
3. Zet `enabled=true` in `config/bol-price-cycle.json` en commit op main.
4. Onderzoek een eventueel eerder API-circuit-breakerprobleem vóór expliciet
   hervatten. De bestaande API-workflow/code en alle credentials blijven beschikbaar.

Geen destructieve terugdraaiing van producten, prijzen of historie. De API-writer
behoudt zijn bescherming tegen oudere prijzen. Hervat nooit beide automatische
writers tegelijk.
