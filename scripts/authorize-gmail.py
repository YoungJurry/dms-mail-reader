#!/usr/bin/env python3
"""Authorize one Gmail mailbox for the DMS Mail Reader plugin."""

import argparse
import json
import sys

from gmail_oauth import authorize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", help="Google Desktop OAuth client ID (after first sign-in)")
    parser.add_argument("--client-json", help="Downloaded Google Desktop OAuth JSON (first sign-in)")
    parser.add_argument("--username", required=True, help="Full Gmail email address")
    args = parser.parse_args()
    if not args.client_id and not args.client_json:
        parser.error("provide --client-id or --client-json")
    try:
        client_id = args.client_id
        client_secret = None
        if args.client_json:
            with open(args.client_json, encoding="utf-8") as handle:
                installed = json.load(handle)["installed"]
            if client_id and client_id != installed["client_id"]:
                raise RuntimeError("--client-id does not match the downloaded Desktop client")
            client_id = installed["client_id"]
            client_secret = installed["client_secret"]
        authorize(client_id, args.username, client_secret=client_secret)
    except (RuntimeError, KeyError, ValueError, OSError) as exc:
        print("Gmail authorization failed: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nGmail authorization canceled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
