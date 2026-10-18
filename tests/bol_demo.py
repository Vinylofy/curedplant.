"""Generate clearly synthetic feed data, never a substitute for live evidence."""
import csv
import json
from pathlib import Path
import sys


def generate(path, count=20):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    profile = json.loads((Path(__file__).parents[1] / "config/bol-feed.example.json").read_text())
    headers = [profile[k] for k in ["product_id", "ean", "title", "format"]]
    for fields in profile["offers"].values():
        headers.extend(fields.values())
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, headers, delimiter="|")
        writer.writeheader()
        for i in range(count):
            body = "0000000000" + str(i).zfill(2)
            total = sum(int(v) * (3 if j % 2 == 0 else 1) for j, v in enumerate(reversed(body)))
            ean = body + str((-total) % 10)
            row = {"productId": str(1000000000000000 + i), "ean": ean,
                   "title": f"SYNTHETIC TEST RECORD {i + 1} — NOT A BOL PRODUCT",
                   "Properties.Drager": "LP"}
            for country, fields in profile["offers"].items():
                values = {"price": f"{20 + i}.99" if country == "NL" else f"{22 + i}.49",
                          "shipping": "" if i % 2 else "2.95", "condition": "NEW",
                          "deliverable": "true", "seller_type": "B" if i % 2 else "P",
                          "url": f"https://www.bol.com/{country.lower()}/nl/p/synthetic-test/{1000000000000000 + i}/"}
                row.update({header: values[field] for field, header in fields.items()})
            writer.writerow(row)


if __name__ == "__main__":
    generate(sys.argv[1])
