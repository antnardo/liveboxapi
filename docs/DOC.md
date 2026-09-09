# liveboxapi — documentation

- [The protocol, in one page](#the-protocol-in-one-page)
- [Sessions](#sessions)
- [Credentials](#credentials)
- [Reading](#reading)
- [Writing](#writing)
- [Batching](#batching)
- [Introspection](#introspection)
- [Traps this package handles for you](#traps-this-package-handles-for-you)
- [Model differences](#model-differences)
- [Command line](#command-line)

## The protocol, in one page

The box exposes JSON-RPC over HTTP at `/ws`. A call names a *service* — an
object of its datamodel — and a *method*:

```json
{"service": "NMC", "method": "getWANStatus", "parameters": {}}
```

Authentication opens a *context*: one POST with the admin credentials returns a
context identifier, which every later call repeats in two headers. This package
does that for you, lazily, on the first call.

Two peculiarities shape everything else. Answers put their payload sometimes in
`status` and sometimes in `data`, with no rule to predict which — `call()` tries
both. And **failures come back as HTTP 200** with an `errors` list in the body,
which is why `call()` raises rather than returning something that looks fine.

## Sessions

```python
from liveboxapi import Livebox

box = Livebox(password="…")          # nothing sent yet
print(box.network.public_ip())       # logs in here
```

As a context manager, the login happens on entry and the connection pool closes
on exit:

```python
with Livebox(password="…") as box:
    ...
```

The context is renewed automatically if the box drops it, which it does after a
reboot or a long idle. You never handle that.

Areas: `box.system`, `box.network`, `box.dhcp`, `box.firewall`, `box.wifi`,
`box.schedule`, `box.voice`. Plumbing: `box.call`, `box.raw`, `box.batch`,
`box.introspect`, `box.functions`, `box.parameters`.

## Credentials

Resolved in order — explicit argument, environment, password manager:

| Source | How |
| --- | --- |
| explicit | `Livebox(password="…")` |
| environment | `LIVEBOX_PASSWORD`, plus `LIVEBOX_URL` and `LIVEBOX_USER` |
| 1Password | `LIVEBOX_OP_ITEM` and `LIVEBOX_OP_VAULT`, read through the `op` command |

`url` and `user` passed explicitly still override what a resolver found, which
is how you reach a second box that shares a stored password.

To add your own store, append a callable returning `Credentials | None`:

```python
from liveboxapi import credentials

credentials.RESOLVERS.append(my_resolver)
```

The 1Password path reads the item in **one** invocation and retries once: that
command is occasionally slow or fails outright, and a single transient failure
should not take down a scheduled job.

## Reading

```python
box.system.firmware_version()      # 'SGW7-fr-G03.R09.C02_02'
box.system.uptime()                # timedelta
box.system.backup_age()            # how stale the operator-side backup is

box.network.wan_status()           # WanStatus, .up and .fibre_operational
box.network.gpon()                 # optical power, temperature, negotiated rate
box.network.devices()              # connected devices
box.network.unknown_devices(known) # active, undeclared, non-randomised

box.dhcp.static_leases()           # reservations, sorted by address
box.dhcp.dynamic_leases()          # addresses handed out without a reservation

box.firewall.port_forwardings()                # every redirection
box.firewall.port_forwardings(origin="upnp")   # what opened itself

box.wifi.interfaces()              # per band: security mode, WPS, status
box.schedule.blocked_devices()     # cut off from the internet
box.voice.unviewed_count()         # missed calls nobody looked at
```

Everything returns frozen dataclasses rather than raw dictionaries, so a
renamed field in a firmware update breaks in one place instead of everywhere.

## Writing

Open the session read-only whenever a program has no business changing
anything, and the guard refuses before anything reaches the network:

```python
with Livebox(password="…", readonly=True) as box:
    box.firewall.set_upnp(False)     # ReadOnlyError
```

Otherwise:

```python
box.dhcp.add_static_lease("00:00:5E:00:53:01", "192.168.1.10")
box.dhcp.set_lease_time(86400)

box.firewall.set_port_forwarding("Plex", "192.168.1.20", internal_port="32400")
box.firewall.set_pinhole("ssh", "2001:db8::44", destination_port="22")
box.firewall.set_level("Medium")
box.firewall.set_respond_to_ping(ipv4=False, ipv6=False)

box.wifi.set_wps(False)
box.wifi.set_guest(False)

box.schedule.block("00:00:5E:00:53:03")

box.system.change_password("admin", "…")
box.system.launch_backup()
```

Changing the LAN merges with what is there, so a lease-time change cannot
reset the subnet by omission:

```python
box.network.set_lan_config(DHCPMinAddress="192.168.1.100", DHCPMaxAddress="192.168.1.199")
```

## Batching

Opening a session costs a round trip and a password check. Twenty readings one
process at a time are measured in minutes; the same twenty in one session take
seconds.

```python
state = box.batch([
    {"key": "wan", "service": "NMC", "method": "getWANStatus"},
    {"key": "upnp", "service": "UPnP-IGD", "method": "get"},
    {"key": "ping", "service": "Firewall", "method": "getRespondToPing",
     "parameters": {"sourceInterface": "data"}},
])
```

Responses come back whole, errors included: a batch is usually an audit, and one
unsupported method should not lose the other answers.

## Introspection

The box describes itself. This is the difference between guessing an API from a
post written for another model and reading it off the device you own:

```python
for signature in box.functions("Firewall", writes_only=True):
    print(signature)
# setFirewallLevel(string level)
# setPortForwarding(string id, string origin, …)
# deletePinhole(string id, string origin)
# commit()

box.parameters("UPnP-IGD")     # {'Enable': False, …}
box.introspect("NMC", depth=-1)  # the whole subtree, large
```

Existing tooling believes the operator disabled this from the Wi-Fi 7 model
onwards and gates it on the model number without retesting. On a Livebox W7
running `SGW7-fr-G03.R09` the same REST route answers normally, including the
full subtree. If it fails on your box, please open an issue with the firmware
string from `box.system.firmware_version()`.

## Traps this package handles for you

| Trap | What happens without it |
| --- | --- |
| Reservations report a wrong `MACAddress`; the real one is in `LeasePath` | Your inventory is quietly wrong |
| `addStaticLease` ignores lowercase addresses | The call reports success and does nothing |
| Port and pinhole writes need `Firewall:commit`; levels, DMZ and ping do not | The rule exists in the configuration and not in the packet filter |
| Protocols are IANA numbers, not names | The rule is rejected, sometimes silently |
| Deleting a rule wants the identifier including its `webui_` prefix | Nothing is deleted |
| Generic `set` nests its argument under `parameters` | The write is ignored |
| Introspection needs slashes in the path and the session headers | "Permission denied", which is not an authorisation problem |
| Errors ride inside HTTP 200 | Failed writes look like successes |
| An identical reservation is reported as an error | Idempotent configuration crashes |

## Model differences

The box line matters, and the firmware string names it: `SG70` is a Livebox 7,
`SGW7` the Wi-Fi 7 variant. Observed differences:

- Wi-Fi interfaces are numbered on the Livebox 6 and 7 (`vap2g0priv0`) and not
  on the W7 (`vap2g0priv`). `box.wifi.interfaces()` discovers whichever exists,
  asking the bridges first and falling back to probing known names.
- `NMC.Wifi:setWPSEnable` exists on the W7; on the Livebox 7 WPS is per
  interface.
- The LAN bridge accepts `DHCPAuthoritative` on the W7.

Firewall methods have been identical from the Livebox 4 onwards, so older
documentation stays valid for that part.

## Command line

```console
livebox health          # link, fibre, services, uptime
livebox devices --all   # connected devices, randomised addresses flagged
livebox leases          # reservations
livebox dynamic         # addresses handed out without one
livebox nat             # redirections, and how many UPnP opened
livebox firewall        # levels, UPnP, pinholes, DMZ, ping, remote admin
livebox wifi            # radios, interfaces, security
livebox calls           # missed calls
livebox blocked         # devices cut off
livebox functions Firewall --writes
livebox call NMC getWANStatus
livebox batch < calls.json
livebox reserve AA:BB:CC:DD:EE:FF 192.168.1.50
livebox block 00:00:5E:00:53:03
```

Read subcommands open a read-only session; only the ones that name a change can
write.
