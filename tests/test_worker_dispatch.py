import unittest

from scripts.workers.run_catalog_price import command_for as catalog_command
from scripts.workers.run_ean_detail import command_for as detail_command


class WorkerDispatchTests(unittest.TestCase):
    def test_catalog_workers_have_commands(self):
        for worker in (
            "bobsvinyl", "everythingjazz", "fiftiesstore", "musiconvinyl",
            "myrecordstore", "northendhaarlem", "platenzaak", "platomania",
            "recordsonvinyl", "sounds", "soundshaarlem", "soundsvenlo", "variaworld",
        ):
            command = catalog_command(worker, 1)
            self.assertIn("scripts.scrapers.usf.jobs", " ".join(command))
            self.assertNotIn("--write", command)

    def test_detail_workers_have_commands(self):
        for worker in (
            "bobsvinyl", "everythingjazz", "imusic", "jpc", "myrecordstore",
            "northendhaarlem", "platenzaak", "soundshaarlem", "soundsvenlo",
        ):
            command = detail_command(worker, 1)
            self.assertIn("scripts.scrapers.usf.jobs", " ".join(command))

    def test_unknown_worker_is_rejected(self):
        with self.assertRaises(SystemExit):
            catalog_command("not-a-shop", 1)
        with self.assertRaises(SystemExit):
            detail_command("not-a-shop", 1)


if __name__ == "__main__":
    unittest.main()
