#!/usr/bin/env python3
"""Authorize one Outlook.com mailbox for the DMS Mail Reader plugin."""

import argparse
import sys

from outlook_oauth import authorize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True, help="Entra Application (client) ID")
    parser.add_argument("--username", required=True, help="Full Outlook.com email address")
    args = parser.parse_args()
    try:
        authorize(args.client_id, args.username)
    except (RuntimeError, KeyError, ValueError) as exc:
        print("Outlook authorization failed: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOutlook authorization canceled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
