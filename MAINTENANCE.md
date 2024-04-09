# Maintenance

This document describes how to maintain the CI for electron riscv.

## Runner Host

On the runner host, a systemd-nspawn container is used to run the GitHub Actions runner.

`/etc/systemd/nspawn/bookworm.nspawn`:

```ini
[Exec]
PrivateUsers=off
ResolvConf=off

[Network]
VirtualEthernet=no

[Files]
Bind=/home/kxxt/Workspaces/chromium
Bind=/home/kxxt/.cache/ccache
Bind=/home/kxxt/.git_cache
Bind=/home/kxxt/depot_tools
Bind=/data/electron-ci:/home/kxxt/electron-ci
```

`/etc/systemd/system/systemd-nspawn@bookworm.service.d/override.conf`:

This override is needed only because I put the rootfs outside of `/var/lib/machines`.

`systemd-nspawn@bookworm.service` is enabled.

```ini
[Service]
ExecStart=
ExecStart=systemd-nspawn --quiet --keep-unit --boot --link-journal=try-guest --network-veth -D /data/nspawn-containers/bookworm -U --settings=override --machine=%i
```

## Nspawn Runner 

FIXME: Create a systemd service for the github runner.

