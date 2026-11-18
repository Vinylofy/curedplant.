# Price history retention: 34 days

Vanaf **19 november 2026 00:00 UTC** gebruikt de bestaande E:-archiefworkflow
een bewaartermijn van 34 dagen voor `public.price_history`. Tot dat moment blijft
de oude grens van 90 dagen actief. `raw_shop_scrapes` blijft ongewijzigd op 30
dagen.

De geplande workflow draait om 00:35, 06:35, 12:35 en 18:35 UTC. Iedere run
kopieert eerst begrensde batches naar `E:\Vinylofy\database-archive`, valideert
checksum, rij-identiteiten en herstelvorm, en verwijdert daarna uitsluitend
geverifieerde archiefbestanden. De laatste prijswaarneming per product en winkel
blijft door de bestaande veiligheidsregel behouden.

Voor de overgang van 90 naar 34 dagen is de geplande capaciteit tijdelijk ruim
genoeg ingesteld op maximaal 500 exportbatches van 2.000 regels en maximaal 500
cleanupbestanden per run. Lege achterstanden zijn een no-op. Checkpoints en
cleanupmarkers houden alle stappen hervatbaar en idempotent.
