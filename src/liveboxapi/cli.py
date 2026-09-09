"""The ``livebox`` command.

A library is the right shape for a router client, but half the uses are one-off
questions — what is my public address, which devices are connected, is the fibre
level dropping. Those deserve a command rather than a Python session.

Everything here is read-only by default. Writes live behind subcommands that
name what they change, and the session is opened read-only unless one of them
is used: a typo in a read command cannot reconfigure anything.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from liveboxapi import Livebox, __version__
from liveboxapi.errors import LiveboxError, ReadOnlyError

__all__ = ["main"]

_WRITE_COMMANDS = {"reserve", "unreserve", "block", "unblock", "call", "set-wifi", "set-wps"}


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _cmd_health(box: Livebox, _args: argparse.Namespace) -> int:
    health = box.health()
    print(f"WAN            {'up' if health['wan_up'] else 'DOWN'}  {health['public_ip']}")
    print(f"IPv6 prefix    {health['ipv6_prefix'] or '—'}")
    print(
        f"GPON           {health['gpon_state']}  rx {health['fibre_rx_dbm']} dBm  "
        f"tx {health['fibre_tx_dbm']} dBm  {health['fibre_temperature_c']} °C"
    )
    print(f"IPTV / VoIP    {health['iptv']} / {health['voip']}")
    print(f"Missed calls   {health['missed_calls']}")
    print(f"Firmware       {health['firmware']}")
    print(f"Uptime         {health['uptime_days']} days")
    return 0


def _cmd_devices(box: Livebox, args: argparse.Namespace) -> int:
    devices = box.network.devices(active_only=not args.all)
    print(f"{'IP':16}{'MAC':20}{'NAME':28}{'TYPE'}")
    for device in sorted(devices, key=lambda d: d.ipv4):
        flag = " (random MAC)" if device.has_private_mac else ""
        print(f"{device.ipv4:16}{device.mac:20}{device.name[:26]:28}{device.device_type}{flag}")
    print(f"\n{len(devices)} devices")
    return 0


def _cmd_leases(box: Livebox, _args: argparse.Namespace) -> int:
    leases = box.dhcp.static_leases()
    for lease in leases:
        print(f"{lease.ip:16}{lease.mac}")
    print(f"\n{len(leases)} reservations")
    return 0


def _cmd_dynamic(box: Livebox, _args: argparse.Namespace) -> int:
    """Devices holding an address without a reservation — the ones you did not declare."""
    for lease in box.dhcp.dynamic_leases():
        state = "active" if lease.active else "idle"
        print(f"{lease.ip:16}{lease.mac:20}{lease.friendly_name[:24]:26}{state}")
    return 0


def _cmd_nat(box: Livebox, _args: argparse.Namespace) -> int:
    rules = box.firewall.port_forwardings()
    for rule in rules.values():
        protocols = "/".join(rule.protocol_names)
        state = "on " if rule.enabled else "OFF"
        print(
            f"{state} {rule.external_port:>7} {protocols:8} -> {rule.destination:16}"
            f"{rule.internal_port:>7}  {rule.description}"
        )
    upnp = box.firewall.port_forwardings(origin="upnp")
    print(f"\n{len(rules)} rules, {len(upnp)} of them opened by UPnP")
    return 0


def _cmd_firewall(box: Livebox, _args: argparse.Namespace) -> int:
    ping = box.firewall.respond_to_ping()
    print(f"level          {box.firewall.level()} (IPv4) / {box.firewall.ipv6_level()} (IPv6)")
    print(f"UPnP           {'on' if box.firewall.upnp_enabled() else 'off'}")
    print(f"pinholes       {len(box.firewall.pinholes())}")
    print(f"DMZ            {len(box.firewall.dmz())}")
    print(f"answers ping   v4 {ping.get('enableIPv4')}  v6 {ping.get('enableIPv6')}")
    print(f"remote admin   {'ON' if box.firewall.remote_access().get('Enable') else 'off'}")
    return 0


def _cmd_wifi(box: Livebox, _args: argparse.Namespace) -> int:
    print(f"radios         {'on' if box.wifi.enabled() else 'off'}")
    print(f"WPS            {'ON' if box.wifi.wps_enabled() else 'off'}")
    print(f"guest network  {'ON' if box.wifi.guest_enabled() else 'off'}")
    for interface in box.wifi.interfaces():
        print(
            f"  {interface.name:16}{interface.band:8}{interface.status:8}"
            f"{interface.security_mode:28}WPS {'on' if interface.wps_enabled else 'off'}"
        )
    return 0


def _cmd_calls(box: Livebox, args: argparse.Namespace) -> int:
    for call in box.voice.missed_calls(limit=args.limit):
        seen = "seen" if call.viewed else "NEW "
        when = call.start_time.strftime("%Y-%m-%d %H:%M") if call.start_time else "?"
        print(f"{seen}  {when}  {call.number}")
    return 0


def _cmd_blocked(box: Livebox, _args: argparse.Namespace) -> int:
    for entry in box.schedule.entries():
        state = "BLOCKED" if entry.blocked else "allowed"
        print(f"{entry.mac:20}{state}")
    return 0


def _cmd_functions(box: Livebox, args: argparse.Namespace) -> int:
    """Ask the box what an object can do — the answer no documentation gives reliably."""
    for signature in box.functions(args.path, writes_only=args.writes):
        print(signature)
    return 0


def _cmd_health_json(box: Livebox, _args: argparse.Namespace) -> int:
    _print_json(box.health())
    return 0


def _cmd_call(box: Livebox, args: argparse.Namespace) -> int:
    _print_json(box.raw(args.service, args.method, json.loads(args.parameters)))
    return 0


def _cmd_batch(box: Livebox, args: argparse.Namespace) -> int:
    spec = json.loads(args.spec) if args.spec else json.load(sys.stdin)
    if not isinstance(spec, list):
        raise SystemExit("batch expects a JSON list of calls")
    _print_json(box.batch(spec))
    return 0


def _cmd_reserve(box: Livebox, args: argparse.Namespace) -> int:
    box.dhcp.add_static_lease(args.mac, args.ip)
    print(f"reserved {args.ip} for {args.mac.upper()}")
    return 0


def _cmd_unreserve(box: Livebox, args: argparse.Namespace) -> int:
    box.dhcp.delete_static_lease(args.mac)
    print(f"reservation removed for {args.mac.upper()}")
    return 0


def _cmd_block(box: Livebox, args: argparse.Namespace) -> int:
    box.schedule.block(args.mac)
    print(f"{args.mac.upper()} can no longer reach the internet")
    return 0


def _cmd_unblock(box: Livebox, args: argparse.Namespace) -> int:
    box.schedule.unblock(args.mac)
    print(f"{args.mac.upper()} may reach the internet again")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="livebox", description="Talk to an Orange Livebox.")
    parser.add_argument("--version", action="version", version=f"liveboxapi {__version__}")
    parser.add_argument("--url", help="box address, default http://192.168.1.1/")
    parser.add_argument("--user", help="admin account, default admin")
    parser.add_argument(
        "--password",
        help="admin password; prefer LIVEBOX_PASSWORD or the password manager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler, help_text: str) -> argparse.ArgumentParser:
        entry = sub.add_parser(name, help=help_text)
        entry.set_defaults(handler=handler)
        return entry

    add("health", _cmd_health, "one-screen summary of the link and the services")
    add("health-json", _cmd_health_json, "same, as JSON for monitoring")
    devices = add("devices", _cmd_devices, "connected devices")
    devices.add_argument("--all", action="store_true", help="include devices seen but offline")
    add("leases", _cmd_leases, "DHCP reservations")
    add("dynamic", _cmd_dynamic, "addresses handed out without a reservation")
    add("nat", _cmd_nat, "inbound port redirections")
    add("firewall", _cmd_firewall, "levels, UPnP, pinholes, DMZ, ping, remote admin")
    add("wifi", _cmd_wifi, "radios, interfaces and their security")
    calls = add("calls", _cmd_calls, "missed calls")
    calls.add_argument("--limit", type=int, default=10)
    add("blocked", _cmd_blocked, "devices cut off from the internet")

    functions = add("functions", _cmd_functions, "ask the box what an object can do")
    functions.add_argument("path", help="datamodel object, e.g. Firewall or NMC.Wifi")
    functions.add_argument("--writes", action="store_true", help="only methods that change state")

    call = add("call", _cmd_call, "raw API call")
    call.add_argument("service")
    call.add_argument("method")
    call.add_argument("parameters", nargs="?", default="{}")

    batch = add("batch", _cmd_batch, "many calls in one session, JSON in, JSON out")
    batch.add_argument("spec", nargs="?", help="JSON list; read from stdin when absent")

    reserve = add("reserve", _cmd_reserve, "create a DHCP reservation")
    reserve.add_argument("mac")
    reserve.add_argument("ip")
    unreserve = add("unreserve", _cmd_unreserve, "remove a DHCP reservation")
    unreserve.add_argument("mac")

    block = add("block", _cmd_block, "cut a device off the internet")
    block.add_argument("mac")
    unblock = add("unblock", _cmd_unblock, "restore a device's internet access")
    unblock.add_argument("mac")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    box = Livebox(
        url=args.url,
        user=args.user,
        password=args.password,
        readonly=args.command not in _WRITE_COMMANDS,
    )
    try:
        with box:
            return int(args.handler(box, args))
    except ReadOnlyError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except LiveboxError as exc:
        print(f"the box refused: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
