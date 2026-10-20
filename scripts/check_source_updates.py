#!/usr/bin/env python3
"""Check saved announcements against official pages without importing data."""
import argparse
import json
from pathlib import Path
import sys

from ru_source_updates.checker import run_check


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path, help='new directory for this check')
    parser.add_argument('--state-file', type=Path, help='read-only prior check manifest or ledger with a sources array')
    parser.add_argument('--offline', action='store_true', help='inventory saved sources without claiming an official check')
    parser.add_argument('--timeout', type=float, default=15, help='request time limit in seconds (0 < N <= 120)')
    parser.add_argument('--index-url', help='optional official index page; links are queued for review only')
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error('--timeout must be greater than 0 and at most 120 seconds')
    try:
        manifest = run_check(**vars(args))
    except (OSError, ValueError) as error:
        parser.exit(2, f'check_source_updates: {error}\n')
    print(json.dumps({'manifest': str(args.output_dir / 'check-manifest.json'),
                      'mode': manifest['mode'], 'source_count': manifest['source_count'],
                      'failed_attempt_count': manifest['failed_attempt_count'],
                      'site_freshness': manifest['site_freshness']}))
    return 1 if manifest['failed_attempt_count'] else 0


if __name__ == '__main__':
    sys.exit(main())
