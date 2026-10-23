"""Read-only coverage check using the production collector and existing identities."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.workers.myrecordstore_targets import registered_offers
from scripts.workers.price_evidence import assess, url_key


def main():
    targets = registered_offers()
    limit = int(os.environ.get('MYRECORDSTORE_AUDIT_EXISTING_LIMIT', '20'))
    if limit < 0:
        raise ValueError('Existing offer audit limit must be nonnegative')
    reviewed = targets[:limit] if limit else targets
    known = {url_key(row['source_url']) for row in targets}
    reviewed_keys = {url_key(row['source_url']) for row in reviewed}
    with tempfile.TemporaryDirectory() as directory:
        evidence = Path(directory) / 'prices.jsonl'
        identities = Path(directory) / 'existing.json'
        identities.write_text(json.dumps(reviewed))
        env = dict(os.environ, CUREDPLANT_PRICE_EVIDENCE=str(evidence), DATABASE_URL='',
                   PGOPTIONS='-c default_transaction_read_only=on')
        result = subprocess.run([
            sys.executable, '-u', '-m',
            'scripts.scrapers.usf.jobs.refresh_myrecordstore_listing_prices',
            '--max-pages', '0', '--existing-offers-file', str(identities),
        ], env=env, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(result.stdout, flush=True)
        records = [json.loads(line) for line in evidence.read_text().splitlines()] if evidence.exists() else []
    prices, assessment = assess(records)
    report = {
        'database_writes': 0,
        'status': assessment['status'] if result.returncode == 0 else 'red',
        'source_returncode': result.returncode,
        'registered_eligible_prices': len(targets),
        'targeted_existing_offers': len(reviewed),
        'targeted_existing_offers_found': sum(url_key(row['source_url']) in reviewed_keys for row in prices),
        'current_listing_prices': len(prices),
        'registered_prices_found': sum(url_key(row['source_url']) in known for row in prices),
        'errors': assessment['errors'],
        'source_error': result.stdout[-700:] if result.returncode else None,
        'samples': [{'url': row['source_url'], 'price': row['price']} for row in prices[:3]],
    }
    text = json.dumps(report).replace('%', '%25').replace('\n', '%0A').replace('\r', '%0D')
    print('::notice title=My Record Store catalogue coverage audit::' + text)
    return 0 if report['status'] == 'green' else 1


if __name__ == '__main__':
    raise SystemExit(main())
