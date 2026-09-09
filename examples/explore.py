"""Ask the box what it can do, instead of guessing from someone else's model.

Firmware differs more than documentation admits: the same setting lives under a
different object, or a method exists on one model and not on another. Rather
than trusting a recipe, print the methods your own box exposes.

    python examples/explore.py Firewall
    python examples/explore.py NMC.Wifi --writes
    python examples/explore.py DHCPv4.Server.Pool.default
"""

import argparse
import sys

from liveboxapi import Livebox
from liveboxapi.errors import LiveboxError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="datamodel object, dots or slashes both work")
    parser.add_argument("--writes", action="store_true", help="only the methods that change state")
    parser.add_argument("--values", action="store_true", help="also print the current parameters")
    args = parser.parse_args()

    with Livebox(readonly=True) as box:
        try:
            signatures = box.functions(args.path, writes_only=args.writes)
        except LiveboxError as exc:
            # A typo in the object name lands here, with code 196618.
            print(f"the box does not know {args.path!r}: {exc}", file=sys.stderr)
            return 1

        for signature in signatures:
            print(signature)

        if args.values:
            print()
            for name, value in box.parameters(args.path).items():
                print(f"{name} = {value!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
