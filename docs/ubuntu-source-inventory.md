# Ubuntu source inventory

The following Ubuntu/hosted scraper workflows were present in
`Vinylofy/Vinylofy` when this migration was prepared and their Python source
is included here under `scripts/scrapers/`:

`blackvinyl`, `shop-atthemovies`, `shop-bobsvinyl`, `shop-dgmoutlet`,
`shop-getbackmusic`, `shop-grooverecords-pilot`, `shop-platenzaak-listing`,
`shop-platenzaak-enrich`, `shop-viprecords-pilot`, `usf-bobsvinyl`,
`usf-colouredvinyl`, `usf-dgmoutlet`, `usf-everythingjazz-detail`,
`usf-everythingjazz-listing`, `usf-fiftiesstore`, `usf-imusic-exposures`,
`usf-imusic`, `usf-jpc`, `usf-musiconvinyl`, `usf-myrecordstore`,
`usf-northendhaarlem`, `usf-platenzaak`, `usf-platomania`,
`usf-recordsonvinyl`, `usf-shop3345`, `usf-sounds`, `usf-soundshaarlem`,
`usf-soundsvenlo`, and `usf-suburban`.

The new two-lane workflows expose the workers with a matrix so each worker is
an independently visible Action job. Workers not yet present in the explicit
dispatcher maps are retained in the source tree and should be added only after
their price/detail CLI split is verified. This is intentional: an unverified
worker must not silently write to production.
