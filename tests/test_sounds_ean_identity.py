from scripts.scrapers.usf.jobs import detail_sounds
from scripts.workers.ean_sources import EanSource


def test_sounds_detail_title_supplies_artist_and_album_for_ean_promotion():
    assert detail_sounds.extract_artist_title(
        "George Michael | Faith | 2 LP | 0196588342417 | Sounds"
    ) == ("George Michael", "Faith")


def test_sounds_detail_title_keeps_punctuation_in_identity():
    assert detail_sounds.extract_artist_title(
        "Various | Pride & Prejudice | 1 LP | 0028948712274 | Sounds"
    ) == ("Various", "Pride & Prejudice")


def test_sounds_detail_title_refuses_ambiguous_or_error_pages():
    assert detail_sounds.extract_artist_title("ERROR 403 - Forbidden!") == (None, None)
    assert detail_sounds.extract_artist_title("Artist | Album | Unexpected | Data") == (None, None)


def test_sounds_ean_source_returns_complete_canonical_identity():
    html = "<html><head><title>George Michael | Faith | 2 LP | 0196588342417 | Sounds</title></head><body>EAN 0196588342417</body></html>"

    class Response:
        text = html
        content = html.encode()
        url = "https://www.sounds.nl/detail/4540945/lp/george_michael/faith"
        status_code = 200

    source = EanSource("sounds", sleeper=lambda _: None)
    source.get = lambda _: Response()
    try:
        result = source.detail({"source_url": Response.url, "payload": {}})
    finally:
        source.close()

    assert result["ean"] == "00196588342417"
    assert result["artist"] == "George Michael"
    assert result["title"] == "Faith"
    assert result["source_title_raw"].startswith("George Michael | Faith")
