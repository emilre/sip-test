# Asterisk Phase 1 — Local SIP Calls

Two SIP softphones calling each other over the local network, plus demo extensions.

## Quick Start

Copy these files to your Linux server (Ubuntu 22.04/24.04 or Debian 12), then:

```bash
sudo bash setup.sh
```

That's it. The script installs Asterisk, deploys configs, opens firewall ports, and restarts the service.

## Softphone Setup

Install **Zoiper** (free) or **Linphone** (free) on two devices.

| Setting   | Phone A         | Phone B         |
|-----------|-----------------|-----------------|
| Username  | `100`           | `101`           |
| Password  | `phone100pass`  | `phone101pass`  |
| Domain    | `<SERVER_IP>`   | `<SERVER_IP>`   |
| Port      | `5060`          | `5060`          |
| Transport | UDP             | UDP             |

Find your server IP with: `hostname -I`

## Test Extensions

| Dial | What happens                  |
|------|-------------------------------|
| 100  | Rings Phone A                 |
| 101  | Rings Phone B                 |
| 200  | Plays audio greeting          |
| 300  | Simple IVR menu (press 1 or 2)|
| 400  | Echo test (hear yourself)     |
| 500  | Custom test tone              |

## Debug

```bash
sudo asterisk -rvvv                          # Interactive CLI
sudo asterisk -rx "pjsip show endpoints"     # Check registrations
sudo asterisk -rx "core set verbose 5"       # Verbose call logging
sudo ss -ulnp | grep 5060                    # Verify port is open
```

## Files

- `pjsip.conf` — SIP endpoint/auth configuration
- `extensions.conf` — Dialplan (call routing + demo extensions)
- `setup.sh` — Automated install & deploy script
