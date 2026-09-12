# liveboxapi

A synchronous Python client for **Orange Livebox** routers — the JSON-RPC "sah"
protocol their web interface speaks. Read the state, change the settings, and
ask the box itself what else it can do.

> Unofficial. Not affiliated with, endorsed by, or supported by Orange or
> Sagemcom. *Livebox* is a trademark of Orange; it is used here only to say
> which device this talks to.

```python
from liveboxapi import Livebox

with Livebox(password="…") as box:
    print(box.network.wan_status().ipv4)
    print(box.system.uptime())

    for lease in box.dhcp.static_leases():
        print(lease.ip, lease.mac)
```

```console
$ livebox health
WAN            up  203.0.113.42
IPv6 prefix    2001:db8:1234:5600::/56
GPON           O5_Operation  rx -18.53 dBm  tx 2.14 dBm  58.0 °C
IPTV / VoIP    Available / Up
Missed calls   0
Firmware       SGW7-fr-G03.R09.C02_02
Uptime         14.4 days
```

## Install

```console
pip install liveboxapi
```

Only dependency: `requests`.

## Credentials

Never in your code. The client resolves them, in order:

1. what you pass — `Livebox(password="…")`;
2. the environment — `LIVEBOX_PASSWORD`, plus optional `LIVEBOX_URL` and
   `LIVEBOX_USER`; this is the path for a systemd unit or a container;
3. the 1Password command line — set `LIVEBOX_OP_ITEM` to the item name or uuid
   and `LIVEBOX_OP_VAULT` to its vault, and the client shells out to `op`.

Add your own store by appending to `liveboxapi.credentials.RESOLVERS`.

The factory password is the first eight characters of the Wi-Fi key printed on
the label — which means anyone who has seen the back of the router knows it.
Change it, and keep the new one in a password manager.

## Read-only by default, when you want it

Writing to a home gateway is disruptive in ways that are hard to undo. Open the
session read-only and any `set*`, `add*` or `delete*` raises before it reaches
the network:

```python
with Livebox(password="…", readonly=True) as box:
    box.firewall.set_upnp(False)   # ReadOnlyError
```

The `livebox` command does this on its own: read subcommands open a read-only
session, and only the subcommands that name a change can write.

## What it covers

| Area | Reads | Writes |
| --- | --- | --- |
| `box.system` | model, firmware, uptime, clock, accounts, operator backup | change a password, add or remove an account, trigger or restore the backup |
| `box.network` | WAN status, optical power and temperature, IPv6, LAN, device list | LAN address range, DHCP range and lease time |
| `box.dhcp` | reservations, live leases, pool settings | reserve, edit, delete, lease time |
| `box.firewall` | levels, redirections, pinholes, DMZ, ping, UPnP, remote admin | all of them, with the commit handled for you |
| `box.wifi` | radios, interfaces, security mode, WPS, guest network | radios on/off, WPS, guest, security mode |
| `box.schedule` | per-device internet blocking | block, unblock, remove |
| `box.voice` | call log, missed calls, line status | — |

Anything not wrapped is one call away: `box.call(service, method, params)`.

No session needed to ask an address what it is — `DeviceInfo.get` is the one
service the box serves anonymously:

```python
from liveboxapi import identify

found = identify("http://192.168.1.1/")
if found:
    print(found.product_class, found.firmware)   # Livebox W7  SGW7-fr-G03.R09
```

Useful before fetching a password, and to branch on firmware: interface names
and available methods differ between lines. The anonymous answer is a subset —
model name and hardware version need a session.

## Two things this does differently

**Batch.** Opening a session costs a round trip and a password check. Twenty
readings, twenty sessions, several minutes. The same twenty in one session take
seconds:

```python
state = box.batch([
    {"key": "wan", "service": "NMC", "method": "getWANStatus"},
    {"key": "upnp", "service": "UPnP-IGD", "method": "get"},
    {"key": "leases", "service": "DHCPv4.Server.Pool.default", "method": "getStaticLeases"},
])
```

**Introspection.** The box describes itself — every method of every object, with
its signature. That is the difference between guessing an API from a post
written for another model and reading it off the device in front of you:

```console
$ livebox functions Firewall --writes
setFirewallLevel(string level)
setPortForwarding(string id, string origin, string sourceInterface, …)
setPinhole(string id, string origin, …)
deleteDMZ(string id)
commit()
```

Existing tooling long believed the operator had disabled this from the Wi-Fi 7
model onwards. It had not: on a Livebox W7 running `SGW7-fr-G03.R09.C02_02`,
every *named* object answers normally over the REST route, full subtree
included. Only the two *global* requests — `sysbus/.` and `sysbus/*`, the whole
tree at once — return HTTP 400, which is what earlier tests hit. Confirmed with
the LiveboxMonitor maintainer, who now probes the reply instead of gating on the
model number ([issue #120](https://github.com/p-dor/LiveboxMonitor/issues/120));
the W7 datamodel dump produced with this client is published in that project.
If introspection fails on yours, please open an issue with your firmware
string.

## Alternatives, honestly

Two other projects cover this ground, both actively maintained, and you should
pick on merit:

- [aiosysbus](https://github.com/cyr-ius/aiosysbus) — asynchronous, very broad
  coverage, GPL-3.0. The right choice for asyncio code, and what the Home
  Assistant community component uses.
- [LiveboxMonitor](https://github.com/p-dor/LiveboxMonitor) — a full graphical
  application, MIT, with a reusable API layer inside. The right choice if you
  want a user interface rather than a library.

`liveboxapi` exists for the case neither covers: a small synchronous library,
under a permissive licence, with no GUI toolkit in its dependency tree, usable
from a cron job, an Ansible task or a monitoring script.

## Documentation

Long form in [docs/DOC.md](docs/DOC.md), runnable scripts in
[examples/](examples/).

## Licence

MIT. See [LICENSE](LICENSE).
