"""Check a box against what you decided it should be.

The shape of a useful audit: state the expectations once, read the box once,
compare. Anything that drifts is either something you changed and forgot, or
something that changed by itself — and the second case is the one worth
catching.

Run it from cron and let it be silent when all is well:

    python examples/audit.py || mail -s "the router drifted" me@example.com

The expectations below are a starting point, not a recommendation. Adjust them
to your own setup: the audit is only useful once it states *your* intent.

Note how inbound rules are handled. Counting them and expecting zero would flag
your own deliberate choices as drift, which is how an alert becomes noise.
Instead, declare what you opened and compare sets — then the report answers the
question that matters: is anything open that I did not open?
"""

import sys

from liveboxapi import Livebox

EXPECTED = {
    "firewall level": "Medium",
    "firewall level (IPv6)": "Medium",
    "UPnP enabled": False,
    "answers ping (IPv4)": False,
    "answers ping (IPv6)": False,
    "remote administration": False,
    "Wi-Fi radios": False,
    "guest network": False,
    "WPS": False,
    "rules opened by UPnP": 0,
    "hosts in the DMZ": 0,
}

DECLARED_PINHOLES: set[str] = set()
"""Identifiers of the IPv6 pinholes you opened on purpose.

Publishing a service over IPv6 needs one per host and port, so an empty set
means "I publish nothing". Fill it with what you opened — for example
``{"webui_https", "webui_ssh"}`` — and the audit reports only what appeared
without you.
"""


def observe(box: Livebox) -> dict[str, object]:
    """One reading per expectation, in the order they will be reported."""
    ping = box.firewall.respond_to_ping()
    return {
        "firewall level": box.firewall.level(),
        "firewall level (IPv6)": box.firewall.ipv6_level(),
        "UPnP enabled": box.firewall.upnp_enabled(),
        "answers ping (IPv4)": bool(ping.get("enableIPv4")),
        "answers ping (IPv6)": bool(ping.get("enableIPv6")),
        "remote administration": bool(box.firewall.remote_access().get("Enable")),
        "Wi-Fi radios": box.wifi.enabled(),
        "guest network": box.wifi.guest_enabled(),
        "WPS": box.wifi.wps_enabled(),
        "rules opened by UPnP": len(box.firewall.port_forwardings(origin="upnp")),
        "hosts in the DMZ": len(box.firewall.dmz()),
    }


def main() -> int:
    # Read-only: an audit that can write is an audit you cannot trust.
    with Livebox(readonly=True) as box:
        observed = observe(box)
        pinholes = set(box.firewall.pinholes())

    drifted = {name: value for name, value in observed.items() if value != EXPECTED[name]}
    for name, value in drifted.items():
        print(f"{name}: {value!r}, expected {EXPECTED[name]!r}")

    undeclared = pinholes - DECLARED_PINHOLES
    missing = DECLARED_PINHOLES - pinholes
    for rule in sorted(undeclared):
        print(f"IPv6 pinhole opened without being declared: {rule}")
    for rule in sorted(missing):
        print(f"IPv6 pinhole declared but absent: {rule}")

    if not drifted and not undeclared and not missing:
        print(f"{len(EXPECTED)} settings and {len(pinholes)} pinholes checked, no drift")
    return 1 if (drifted or undeclared or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
