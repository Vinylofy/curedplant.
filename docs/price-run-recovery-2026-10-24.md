# Prijsruns: herstel van 24 oktober 2026

## Bevestigde oorzaken

Sounds Venlo en North End Haarlem stonden nog automatisch op de Windows-runner van de private Vinylofy-repository. De betrokken jobs kregen geen runner toegewezen. De curedplant-workflows waren handmatige Linux-fallbacks; Sounds Venlo liep daar vast op HTTP 403 op pagina 2 en North End op HTTP 403 op de eerste categorie.

De Windows-runner `BOL` in curedplant accepteert de jobs en kan de bronnen lezen. Bij de eerste North End-proef volgde na succesvolle prijsdetectie een `UnicodeEncodeError` bij een vinkje in de log. Python en de bronprocessen gebruiken nu UTF-8.

Tijdelijke fetchfouten konden Sounds Venlo bovendien een pagina laten overslaan. Die pagina wordt nu begrensd opnieuw geprobeerd; een blijvende fout laat de bron falen. North End probeert tijdelijke serverfouten opnieuw op dezelfde URL. Na een blijvende HTTP 403/429 stopt de batch; er worden dan geen nieuwe sessies of IP-adressen geprobeerd.

## Nieuwe prijsplanning

De bestaande `price-soundsvenlo.yml` en `price-northendhaarlem.yml` gebruiken nu de herbruikbare Windows-workflow in curedplant. De geplande runs publiceren alleen gecontroleerde bestaande prijsregels. De broncollector krijgt geen databasecredential.

Dagelijkse Nederlandse wintertijd vanaf 25 oktober 2026:

| Winkel | Tijd | Workflow |
| --- | --- | --- |
| North End Haarlem | 04:35 | `price-northendhaarlem.yml` |
| Variaworld | 05:48 | `price-variaworld.yml` |
| Sounds Venlo | 08:35 | `price-soundsvenlo.yml` |

GitHub bewaart de cronplanning in UTC; Nederlandse zomertijd verschilt daarom één uur. De Windows-bronnen behouden hun minimumintervallen: 30 seconden bij North End en 10 seconden bij Sounds Venlo. De Sounds Venlo-run van 22 oktober bevatte circa 410 listingpagina's; een volledige scan met het huidige interval duurt dus ruim een uur.

De Windows-workflow gebruikt een exact commitarchief in een Windows-veilig tijdelijk pad, blijvende Python-omgevingen, gedeelde browserbestanden en begrensde installatiestappen. Een aparte bewaking onderscheidt een bezette runner van een niet-beschikbare runner en beëindigt onbruikbare wachtrijen. Parallelle bronruns voor dezelfde winkel zijn geblokkeerd.

De automatische planning van de twee oude private Windows-workflows is verwijderd in `Vinylofy/Vinylofy` commit `f0f04e1`. De drie oude wachtende runs zijn geannuleerd. De oude pipelines blijven handmatig beschikbaar. Deze wijziging migreert **prijsactualisatie**; de afzonderlijke EAN/detail-workflows in curedplant blijven handmatig en zijn geen nieuw geactiveerde metadata- of productpublicatieplanning.

## Variaworld-identiteiten

De controle van 23 oktober vond 2.202 actuele bronprijzen en 284 bestaande prijs-URL-matches. Sommige EAN's worden inmiddels onder een ander Variaworld-artikelnummer aangeboden; andere oude aanbiedingen zijn daadwerkelijk uitverkocht of verdwenen.

Voor niet op URL gekoppelde listingprijzen controleert de worker het huidige productmetadata-blok. Alleen een geldige, unieke GTIN uit het eigen nieuwe-vinylblok kan een bestaande aanbieding koppelen. Tweedehandsmarkeringen, conflicterende producten en meerdere huidige aanbiedingen met dezelfde GTIN leveren geen willekeurige keuze op. De prijs blijft uit de listing komen.

De writer controleert de product-GTIN onafhankelijk opnieuw in de database en kan voor een bevestigde vervanging ook de productlink actualiseren. Prijs, availability, productlink en waarnemingstijd worden vóór en na de commit gecontroleerd. Er worden geen publieke producten of nieuwe aanbiedingen aangemaakt en geen EAN's of covers gewijzigd.

Gecontroleerde identiteiten worden met een versie en waarnemingstijd bewaard in `state/variaworld/identities.json`. Positieve bewijzen verlopen na 14 dagen; ontbrekende barcodes worden na 24 uur opnieuw geprobeerd. Een parserwijziging maakt oudere bewijsversies ongeldig. Een latere fout kan de reeds gecontroleerde voortgang behouden. Een tijdelijke netwerkfout of siteblokkade tijdens de optionele identiteitcheck blokkeert de normale verversing van actuele, op URL gekoppelde listingprijzen niet; onbevestigde vervangingen worden overgeslagen en expliciet als uitgesteld gerapporteerd.

## Validatie

81 gerichte lokale tests slagen, inclusief transactietests tegen een afzonderlijke lokale PostgreSQL-container. De bestaande prijswriter-, parser-, transport-, catalogusvolledigheids- en My Record Store-tests zijn meegenomen. De workflowwijzigingen in de private repository zijn met `git diff --check` gecontroleerd; er zijn geen frontendwijzigingen.

Gecontroleerde live pilots:

| Winkel | Bronproef | Gecommitteerd en onafhankelijk gecontroleerd |
| --- | --- | --- |
| Variaworld | 59 geldige listingprijzen, 20 identiteitchecks | 12 bestaande prijsregels; 2 vervangende artikelnummers |
| North End Haarlem | 29 geldige prijzen in één categorie | 3 bestaande prijsregels |
| Sounds Venlo | 100 geldige prijzen op twee pagina's | 1 bestaande prijsregel |

Het aantal bronprijzen is niet hetzelfde als het aantal bestaande publieke aanbiedingen. De Sounds Venlo-proef bewijst geen volledige catalogusdekking. De volledige runs leveren daarvoor aparte tellingen.

Variaworld-voorbeeld: EAN `0888072686212`, A Day To Remember – What Separates Me From You. De oude link `at=9076318000` en prijs €35,90 zijn vervangen door de gecontroleerde actuele link `at=7002617000` en listingprijs €32,00. De publieke database-read bevestigde de nieuwe link, prijs en waarnemingstijd.

## Volledige herstelruns

Bij het schrijven van dit verslag zijn de volledige runs nog niet alle afgerond:

- [North End Haarlem](https://github.com/Vinylofy/curedplant./actions/runs/40125977722)
- [Sounds Venlo](https://github.com/Vinylofy/curedplant./actions/runs/40125981340)
- [Variaworld](https://github.com/Vinylofy/curedplant./actions/runs/40124166086)

Daarom is niet vastgesteld dat alle dashboardaantallen al zijn hersteld. Niet opnieuw waargenomen aanbiedingen krijgen geen kunstmatig nieuwe timestamp. Een groene kleine proef wordt niet als bewijs voor volledige winkelgezondheid gepresenteerd.
