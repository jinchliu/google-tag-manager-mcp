"""Compares the live Tag Manager v2 discovery document with the bundled one.

Exit status 1 when methods, parameters or schemas differ, which means
google-api-python-client needs an upgrade and the coverage test will then
tell which methods lack a tool.

Usage: uv run python scripts/check_discovery_drift.py
"""

import json
import sys
import urllib.request
from typing import Any

from google_tag_manager_mcp import discovery

LIVE_URL = 'https://tagmanager.googleapis.com/$discovery/rest?version=v2'


def method_index(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flattens a discovery document into method id -> (verb, path, parameter names)."""
    found: dict[str, dict[str, Any]] = {}

    def walk(resources: dict[str, Any]) -> None:
        for resource in resources.values():
            for spec in resource.get('methods', {}).values():
                found[spec['id']] = {
                    'httpMethod': spec['httpMethod'],
                    'path': spec['path'],
                    'parameters': sorted(spec.get('parameters', {})),
                }
            walk(resource.get('resources', {}))

    walk(doc['resources'])
    return found


def main() -> int:
    """Prints the differences and returns the exit status."""
    with urllib.request.urlopen(LIVE_URL, timeout=30) as response:
        live = json.load(response)
    bundled = discovery.document()
    print(f'bundled revision {bundled.get("revision")}')
    print(f'live revision {live.get("revision")}')
    drift = 0
    bundled_methods, live_methods = method_index(bundled), method_index(live)
    for method_id in sorted(set(live_methods) - set(bundled_methods)):
        print(f'NEW METHOD  {method_id}')
        drift += 1
    for method_id in sorted(set(bundled_methods) - set(live_methods)):
        print(f'GONE METHOD {method_id}')
        drift += 1
    for method_id in sorted(set(bundled_methods) & set(live_methods)):
        if bundled_methods[method_id] != live_methods[method_id]:
            print(f'CHANGED     {method_id}')
            print(f'    bundled: {bundled_methods[method_id]}')
            print(f'    live:    {live_methods[method_id]}')
            drift += 1
    for name in sorted(set(live['schemas']) | set(bundled['schemas'])):
        if live['schemas'].get(name) != bundled['schemas'].get(name):
            print(f'SCHEMA      {name}')
            drift += 1
    print('no drift' if drift == 0 else f'{drift} difference(s)')
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())
