# Bol NL: automatische prijsbatchketen

De workflow **Curedplant | Price | Bol NL API** (`price-bol-api.yml`) gebruikt de bestaande Marketing Catalog API-importer en gecontroleerde databasewriter. `bol-feed-review.yml` blijft de aparte handmatige FTPS-feeddiagnose. De prijsbatchketen gebruikt Ubuntu; de Windows-machine kan als externe bewaking dienen.

## Ritme

Een geplande start of handmatige `write=true, sample=false, continue_chain=true` verwerkt de eerstvolgende producten vanaf de bestaande cursor. Na een geslaagde batch dispatcht de workflow zelf de volgende. Die volgende workflow wacht zo nodig tot minimaal 30 minuten na de start van de vorige batch. Een trage batch wordt eerst afgemaakt; er wordt nooit een tweede Bol-prijsbatch tegelijk gestart. De cron op `0,30 * * * *` is alleen een vangnet. GitHub kan ook een expliciete dispatch later uitvoeren; dit biedt geen exacte klokgarantie.

Normale vervolgbatches bevatten maximaal 1.500 bestaande, barcode-gecontroleerde vinylproducten. Bij circa 70.000 kandidaten zijn ongeveer 47 batches nodig voor een volledige ronde. Een halfuurritme betekent dus ongeveer één dag per catalogusronde, niet een halve uur per volledige catalogus. Geen snelheidsverhoging of extra parallelle Bol-verzoeken is toegevoegd.

## Veiligheid en hervatten

- De bestaande validatie van NEW-conditie, NL-markt, barcode, artikelprijs en verzending blijft intact. Geen product- of covercreatie.
- De cursor wordt pas opgeslagen na een geslaagde batch. CAS controleert dat de remote cursor sinds het begin niet is veranderd. De automationstatus heeft een eigen CAS-controle.
- `state/bol-api/automation.json` bewaart laatst voltooide batch, volgende toegestane start, foutteller en circuit breaker. Tokens worden nooit opgeslagen.
- Een verbindingsfout, timeout of HTTP 500/502/503/504 mag maximaal twee batchherstarts krijgen, met vijf minuten afkoeling. De cursor blijft dan staan.
- HTTP 401/403/429, schema-/prijsvalidatiefouten, ontbrekende rapportage, onzekere databasewrites en een derde tijdelijke fout stoppen de keten. Cron en watchdog mogen die stop niet negeren.
- Heropen na onderzoek via `resume_chain=true`, samen met `write=true, sample=false, continue_chain=true`. Dit omzeilt geen uitgeschakelde configuratie.
- `config/bol-price-cycle.json` met `enabled=false` pauzeert automatische en volledige write-batches. Probe-runs met `write=false` of `sample=true` starten geen vervolgketen en veranderen geen cataloguscursor.
- Iedere nieuwe batch leest de actuele branch opnieuw, ook als het schedule-event eerder was aangemaakt. Daardoor gebruikt een vertraagde start geen oude cursor uit de vorige batch.

In Actions staan de importer-summary en het artifact `bol-api-prices-<run-id>`, met het prijsrapport en de ketenbeslissing. Een nulresultaat wordt als telling getoond; er wordt niet beweerd dat daarbij prijzen zijn bijgewerkt. Handmatig stopzetten van één job is geen duurzame pauze: gebruik de configuratie of disable de workflow.

## Windows-bewaking

`bol_price_watchdog.py` controleert iedere tien minuten of er een lopende/wachtende prijsworkflow is, of de keten nog toegestaan is en of de laatste geslaagde batch ouder dan 45 minuten is. Alleen een stilgevallen, toegestane keten wordt opnieuw gestart. Een rate-limitstop, expliciete pauze of onbekende jobfailure wordt niet automatisch heropend.

De watchdog gebruikt de bestaande GitHub CLI-authenticatie van de Windows-taakaccount. Een installatiejobtoken wordt niet bewaard: die verloopt en is ongeschikt voor een blijvende taak. Vereist: `gh` lokaal aangemeld met toegang tot curedplant (Contents read, Actions read/write), een blijvende Python 3.11+, en rechten om een Windows Scheduled Task te registreren. Deel geen token in chat.

De handmatige workflow **Vinylofy | Bol | Windows watchdog setup** in `Vinylofy/Vinylofy` controleert deze voorwaarden. Als ze kloppen, installeert hij de taak onder dezelfde account. Anders bewaart hij een credentialvrij `setup-result.json` met wat nog ontbreekt. Hij activeert geen nieuwe credentials en verandert geen Windows-accountrechten.

Voor lokale installatie onder een al geauthenticeerde Windows-account, in PowerShell als administrator:

```powershell
# Voer dit uit vanuit de repository; PythonPath moet naar blijvende Python wijzen.
.\scripts\windows\Install-BolPriceWatchdog.ps1 -ProbeOnly
.\scripts\windows\Install-BolPriceWatchdog.ps1 -PythonPath 'C:\pad\naar\python.exe'
```

Bij een serviceaccount kan de taak zonder interactieve login lopen. Bij een gewone gebruiker gebruikt hij Interactive-logon: die gebruiker moet ingelogd blijven. De taak bevat geen wachtwoord of token; de CLI-authenticatie moet voor diezelfde account beschikbaar zijn. De laatste beslissing staat in `%LOCALAPPDATA%\Vinylofy\BolPriceWatchdog\last-result.json`. Taaknaam: `Vinylofy Bol price watchdog`.

Een extra startcontrole weigert een vorige mislukte/afgebroken writer waarvan de automationstatus niet is opgeslagen (bijvoorbeeld een harde runnercrash of mislukte cursor-publicatie). Onderzoek die run en gebruik daarna expliciet `resume_chain=true`. Dry-runs en sampleprobes veranderen deze controle niet.

## Ingebruikname op 27 oktober 2026

De dry-run [40486726996](https://github.com/Vinylofy/curedplant./actions/runs/40486726996) controleerde de volgende twintig catalogusproducten: status success, twintig gecontroleerd, nul fouten en nul databasewrites. Daarna is de keten aangezet voor de gecontroleerde write-proef en automatische vervolgbatches.

De Windows-installatieflow staat in de private Vinylofy-repository op de bestaande `vinylofy-windows`-runner. Die downloadt de openbare watchdogcode van een vastgelegde curedplant-commit, zonder cross-repository credential. De installatie is pas bewezen wanneer het setup-rapport `installed=true` vermeldt; een wachtende job betekent nog geen actieve bewaking.
