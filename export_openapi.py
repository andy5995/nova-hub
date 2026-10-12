#!/usr/bin/env python3
"""Write the Service API's OpenAPI spec as JSON, for nova-client to vendor.

    .venv/bin/python export_openapi.py ../nova_client/openapi/service-api.json

The Service API only: it is the contract between the hub and every client. The
Management API is the console's and stays out. The file is what
/service/openapi.json serves, so paths are relative to the /service server
entry, and info.version is the hub version it came from.

Regenerate it whenever the Service API changes, and commit it to nova-client
saying which hub tag it came from. nova-client's CI checks its mock hub
against it.
"""

import argparse
import json
import sys
from pathlib import Path


def service_spec() -> dict:
    from main import service_app

    spec = service_app.openapi()
    # Mounted at /service; the served copy gets this from the request's
    # root_path, which an offline export has no request to supply.
    spec["servers"] = [{"url": "/service"}]
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", nargs="?", help="file to write (default: stdout)")
    args = parser.parse_args()

    text = json.dumps(service_spec(), indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
