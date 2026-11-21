# Two Pebbos: home and office

A second Pebbo, for example at the office, is its own instance: its own people, memories, reminders, devices and database. The two instances never read each other's data. The only thing that travels between them is a **handoff** that a person prepared and the owner approved, such as the end-of-day summary from the office to home.

## Run a second instance

On the office computer (or a second core on the same computer for testing), give the instance its own data, port and name:

```sh
cd core
PEBBO_INSTANCE_NAME="Büro" PEBBO_DATA_DIR=~/pebbo-office PEBBO_PORT=8101 \
PEBBO_HOST=0.0.0.0 PEBBO_PUBLIC_URL=http://<address of this computer>:8101 uv run pebbo serve
```

| Variable | Meaning |
| --- | --- |
| `PEBBO_INSTANCE_NAME` | Name shown to the other instance and in handoffs, default `Zuhause` |
| `PEBBO_PUBLIC_URL` | Address the other instance uses to reach this one. Default `http://<host>:<port>`; with `PEBBO_HOST=0.0.0.0` the detected home network address of this computer, as for the phone QR code |
| `PEBBO_HOST` | `0.0.0.0` so the other instance can reach this one |

The instances reach each other on the same network or over a private VPN such as Headscale or Tailscale (addresses 100.64.0.0/10). Pebbo accepts instance calls only from private addresses, never from the public internet, and the control centre stays reachable only on its own computer.

## Pair them

1. In the home control centre, tab **Büro & Zuhause**, click **Code erzeugen**. The code is valid for ten minutes. After five wrong codes in a row, every open code is withdrawn, so nobody on the network can guess it; just create a new one.
2. In the office control centre, same tab, enter the home address (for example `http://192.168.1.10:8100`) and the code, then **Verbinden**.

Each instance now holds its own token for the other. **Trennen** on either side revokes it at once.

## Handoffs

- At the office, say for example "Pebbo, mach mir eine Übergabe für zuhause: Offerte für Müller morgen nachfassen." Pebbo prepares the handoff and says that it waits for approval.
- The office control centre shows the exact content and destination. **Freigeben und senden** sends it, **Ablehnen** discards it. Nothing is sent without this approval.
- At home the handoff becomes a reminder that is due at once for the person with the same name, so Pebbo says it the next time it can speak. Without a matching person it is kept as a household note.
- Both control centres list every handoff with its direction and status as an audit log.
