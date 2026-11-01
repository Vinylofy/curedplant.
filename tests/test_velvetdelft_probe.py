import unittest
from scripts.scrapers.velvetdelft_probe import extract_release_links, GENRES


class VelvetDelftProbeTests(unittest.TestCase):
    def test_extract_and_dedupe(self):
        html = '<a href="/en/release/40211/RADIOHEAD/IN-RAINBOWS/RADIOHEAD/1-LP/634904032418">One</a><a href="/en/release/40211/RADIOHEAD/IN-RAINBOWS/RADIOHEAD/1-LP/634904032418">dup</a><a href="https://evil.example/nl/release/2/x">bad</a>'
        rows = extract_release_links(html, "https://www.velvetdelft.nl/nl/pagina/prog")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["release_id"], "40211")

    def test_all_genres_defined(self):
        self.assertEqual(len(GENRES), 13)

if __name__ == "__main__":
    unittest.main()
