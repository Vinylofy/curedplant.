# bol feed/API source investigation — prepared evidence, not sent

This is a source-data investigation packet. No message has been sent to bol.
It does not assert that every difference is a provider defect: several records
are excluded deliberately by the vinyl/NEW policy, some existing metadata is
unverified, and category differences can explain feed-group membership.

## Reproduction

- Official explicit FTPS host `apm-feed.unftp.bol.com:21`, protected passive data.
- File `product-feed_entertainment-v2.csv.gz`.
- Source MDTM `2026-11-07T20:03:54+00:00` (7 November 2026, 21:03:54 CET).
- SHA-256 `84f38d02c353b60909161d78e9d17437c94034f05c0afbfccc9895ba73dcb66a`.
- 913,984 rows; complete gzip integrity verified.
- Only NEW offers with explicit allowed vinyl carrier values are accepted.
- Read-only audit at `2026-11-07T21:11:22.900899+00:00` compared the same EANs with current
  NL Marketing API best offers and catalogue GPC classifications.

The API sample contains twenty valid current NEW offers. Ten sampled EANs were
absent from the Entertainment source and ten were present but failed explicit
vinyl-carrier selection. Observed GPC categories: eight Book, eleven Music, one
Turntable Element. These are sample facts, not a classification of all gaps.

## Questions for the source owner

1. Which official FTPS feed/group and carrier fields should be used for vinyl
   listings classified as Book or Turntable Element? Is there a supported
   vinyl-specific feed or account filter across these groups?
2. For exact EAN matches with existing LP metadata but CSV `Format=CD`, empty
   Format or mixed media: which independently validated carrier evidence is
   authoritative? Please investigate the listed source product IDs/EANs rather
   than silently changing a canonical MusicBrainz pressing.
3. Can complete NEW NL vinyl coverage be supplied without repeatedly downloading
   the entire international-book feed? That file is 4,780,670,486 compressed bytes
   in the inspected snapshot and exceeds the existing two-GB download guard.
4. Please clarify whether a missing/USED selected feed offer can coexist with a
   current NEW API best offer for the same EAN, including refresh timing and
   selected-offer rules.

## Bounded observed cases

| EAN | FTPS selection result | Current API EUR | Observed API GPC hierarchy |
| --- | --- | ---: | --- |
| 8719262030756 | absent_from_entertainment_feed | 34.99 | Textual/Printed/Reference Materials; Boek |
| 5052442011927 | absent_from_entertainment_feed | 12.64 | Textual/Printed/Reference Materials; Boek |
| 0610371804826 | absent_from_entertainment_feed | 31.73 | Textual/Printed/Reference Materials; Boek |
| 6430080232024 | format_not_proven_vinyl | 24.21 | Audio Visual/Photography; Muziek |
| 5050580771680 | format_not_proven_vinyl | 15.42 | Audio Visual/Photography; Muziek |
| 5036436130924 | format_not_proven_vinyl | 37.07 | Audio Visual/Photography; Muziek |
| 4015698008944 | format_not_proven_vinyl | 33.76 | Audio Visual/Photography; Muziek |
| 0093624857570 | format_not_proven_vinyl | 48.97 | Audio Visual/Photography; Muziek |
| 5060281610645 | absent_from_entertainment_feed | 37.43 | Audio Visual/Photography; Muziek |
| 0196588768019 | absent_from_entertainment_feed | 33.01 | Textual/Printed/Reference Materials; Boek |
| 0610371804444 | absent_from_entertainment_feed | 31.73 | Textual/Printed/Reference Materials; Boek |
| 5036436136827 | format_not_proven_vinyl | 28.99 | Audio Visual/Photography; Muziek |
| 5053760002550 | format_not_proven_vinyl | 43.40 | Audio Visual/Photography; Muziek |
| 4028466922045 | absent_from_entertainment_feed | 26.98 | Textual/Printed/Reference Materials; Boek |
| 4065629733711 | absent_from_entertainment_feed | 32.12 | Textual/Printed/Reference Materials; Boek |
| 0801056818812 | absent_from_entertainment_feed | 38.72 | Audio Visual/Photography; Element voor Platenspeler |
| 0194399834312 | format_not_proven_vinyl | 34.99 | Audio Visual/Photography; Muziek |
| 0634438446804 | absent_from_entertainment_feed | 30.20 | Textual/Printed/Reference Materials; Boek |
| 0610371804284 | format_not_proven_vinyl | 28.09 | Audio Visual/Photography; Muziek |
| 5060708610906 | format_not_proven_vinyl | 45.19 | Audio Visual/Photography; Muziek |

The accompanying [source evidence](bol-ftps-source-evidence.json) contains the
source-product IDs, safe carrier evidence and schema paths. It contains no
credentials, images or product descriptions. Both timestamps must be considered;
a source snapshot and a later live API response are not simultaneous observations.

## Already verified supplemental source metadata

Only file metadata and CSV headers were inspected, not complete book inventories:

| Official file | Compressed bytes |
| --- | ---: |
| `product-feed_dutch-books-v2.csv.gz` | 239,146,659 |
| `product-feed_international-books-v2.csv.gz` | 4,780,670,486 |
| `product-feed_educational-books-v2.csv.gz` | 1,490,833,917 |
| `product-feed_sound-vision-v2.csv.gz` | 293,707,787 |

All four headers contain `ean`, `productId`, `Format`, `BindingCode`, GPC/category
and NL/BE offer fields. A shared header does not prove that the missing EANs occur
in a particular file or that their rows prove vinyl. Header probes consumed only
1,573–2,758 compressed bytes each; complete-file integrity was deliberately not
claimed. No books/accessories have been imported or published.
