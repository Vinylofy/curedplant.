# JPC: onderzoek en herstel, 26 oktober 2026

## Bewijs uit Actions

- Prijsrun [40233157283](https://github.com/Vinylofy/curedplant./actions/runs/40233157283): HTTP 503 op rock-pagina 43, 458 geldige prijsproducten, nul databasewrites. Vier gelijktijdige bronprocessen stopten na de fout. De eerdere run [40176699620](https://github.com/Vinylofy/curedplant./actions/runs/40176699620) stopte eveneens met 503, op rock-pagina 9 (115 prijsproducten, nul writes).
- Laatste volledige groene prijsrun [40076977354](https://github.com/Vinylofy/curedplant./actions/runs/40076977354), 24 oktober: 27.435 prijsproducten, 17.321 bestaande aanbiedingen bijgewerkt én geverifieerd, waarvan 32 gewijzigde prijzen. 10.114 bronproducten hadden geen bestaande URL-match. Er werden 5.067 listingpagina's gelezen in ongeveer 79 minuten.
- EAN-run [40169928765](https://github.com/Vinylofy/curedplant./actions/runs/40169928765), 25 oktober: write=true, 100 geselecteerde/gestarte details, 100 geldige EAN's, nul technische fouten, nul prijswrites, status groen.

503 bewijst een tijdelijke server-/gatewayfout; het bewijs onderscheidt overbelasting, anti-botbescherming en een storing bij JPC niet. Er is geen aangetoonde parser- of databasefout in deze twee rode prijsruns.

## Wijziging

De prijscollector gebruikt twee in plaats van vier parallelle processen en vier in plaats van drie seconden pauze per proces. Dat verlaagt de theoretische aanvraagfrequentie (exclusief responstijd) van 1,33 naar 0,5 per seconde. Alle even/oneven pagina's blijven verdeeld over de twee processen; er worden geen routes geschrapt.

Dezelfde listingpagina wordt maximaal tweemaal opnieuw geprobeerd bij 502/503/504, timeout of connection error, met 60 en 120 seconden wachttijd. Een geldige Retry-After wordt gerespecteerd tot 120 seconden; een langere/onbruikbare waarde beëindigt de poging. 401/403/429 worden niet opnieuw geprobeerd. Blijvende fouten verhinderen nog steeds alle databasewrites; gedeeltelijke brongegevens worden niet groen verklaard. Diagnostiek telt tijdelijke herpogingen.

De JPC-prijslimiet wordt 300 minuten, omdat de laatste volledige scan 5.067 pagina's bevatte. Dit is een veiligheidslimiet, geen geplande looptijd. De dagelijkse prijs- en EAN-planning blijft bestaan. Een volledige rustige scan kan meerdere uren duren. Geen wijziging aan prijsselectie, matching, EAN-dagbudget of databasewriter.

## Validatie

21 JPC-tests en 43 prijsgerelateerde tests slagen (7 database-integratietests overgeslagen zonder testdatabase). Actionlint controleert de twee betrokken prijsworkflows. Een aanvullende begrensde Actions-proef gebruikt write=false; een groene kleine proef bewijst geen volledige catalogusdekking of duurzame oplossing van JPC's 503-responsen.

## Tweede herstelpoging

De eerste begrensde proef [40271798250](https://github.com/Vinylofy/curedplant./actions/runs/40271798250) mislukte na 82 gelezen pagina's: Folk & Americana pagina 1 bleef HTTP 503 geven na twee herpogingen. Er waren 689 geldige prijsproducten en nul databasewrites. Herpogingen op andere pagina's waren deels wel succesvol. De categorie-URL leverde bij een losse controle vanuit de ontwikkelomgeving HTTP 200; dat bewijst geen herstel vanuit GitHub.

De twee Linux-prijsprocessen delen nu één afkoeldeadline in een vergrendeld tijdelijk bestand. Een tijdelijke fout pauzeert daardoor beide ophalers vóór hun volgende listingaanvraag. Een tweede proces kan de wachttijd verlengen, maar nooit verkorten. De wachttijd wordt 60/120 seconden, zonder meer dan drie aanvragen per foutieve pagina. Standalone EAN-discovery heeft geen Linux-lock nodig en behoudt de afzonderlijke EAN-planning. Bestaande aanvragen kunnen bij het ingaan van een pauze nog afronden.

Een nieuwe proef leest maximaal twee pagina's per route met write=false. Volledige catalogusdekking en volledige databaseactualisatie zijn daarmee nog niet bewezen.
