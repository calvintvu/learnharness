# Home server with Podman

Run one LearnHarness instance on `cbox` and use it from any browser on your
Tailscale network. Run Podman as your normal user, without `sudo`. The container
uses rootless Podman's default user mapping, so writes to the bind mounts belong
to your host user and remain accessible to Git. Do not use `sudo podman` with
this setup.

The single service includes Node and Chromium for generated demo verification.
It mounts the checkout's `data/` directory and keeps API keys in the ignored
`.secrets/` directory. Neither directory is included in the image build context.
Port 3000 is exposed only on the server's loopback address.
The server image is built for the `/learnharness` URL prefix so other apps can
share the same HTTPS hostname. This is a build-time setting (`BASE_PATH` in
Compose); local development and desktop builds default to the root URL.

The shared Compose file lives at `~/repos/homelab/compose.yaml`, beside the app
checkouts. Start with the template at `deploy/homelab/compose.yaml` and add other
apps to the shared file later. Keep the Containerfile in the app repository.

## First start

Install Podman and a Compose provider (`podman-compose` or Docker Compose) using
your server distribution's packages. `podman compose` calls that provider.
Check that both are available:

```bash
podman --version
podman compose version
```

In your server checkout:

```bash
cd ~/repos/learnharness
mkdir -p data .secrets
chmod 700 .secrets
mkdir -p ~/repos/homelab
cp -n deploy/homelab/compose.yaml ~/repos/homelab/compose.yaml
cd ~/repos/homelab
podman compose up -d --build learnharness
podman compose logs -f learnharness
```

The first build downloads dependencies, Chromium, and the fonts used by the UI.
Subsequent builds reuse cached layers. Pressing Ctrl+C exits log viewing; the app
continues running after SSH disconnects. No host Node installation is required.

For a local check on the server:

```bash
curl --fail http://127.0.0.1:3000/learnharness/api/settings
```

To access it initially from your laptop or desktop, keep this SSH tunnel open
and visit `http://localhost:3000/learnharness`:

```bash
ssh -L 3000:127.0.0.1:3000 cbox
```

Enter provider keys in LearnHarness's settings, or copy your existing desktop
`auth.json` into `~/repos/learnharness/.secrets/auth.json` on the server before
starting. The app persists settings-page key changes there. Avoid mounting just
the file: saving keys replaces the file atomically and needs a writable parent
directory. Keep the desktop app and any other server process using these data
files closed.

## Access through Tailscale

On `cbox`, after the local check succeeds:

```bash
tailscale serve --bg --set-path=/learnharness http://127.0.0.1:3000/learnharness
tailscale serve status
```

Follow any HTTPS setup link Tailscale prints. Open the resulting
`https://cbox.<your-tailnet>.ts.net/learnharness` address from a device connected to your
tailnet, at home or away. Use the actual URL printed by Tailscale. HTTPS also
allows browser microphone access for dictation. Keep access limited to your
devices using your tailnet policy; LearnHarness does not provide a user-login
boundary. If this server already has Serve routes, inspect `tailscale serve
status` before changing them. This command configures only `/learnharness`.
The backend target also includes `/learnharness` because Serve strips the mount
prefix before appending the target path. No root-level API or asset routes are
needed. The root URL remains available for another service or an app launcher.
Your user needs Tailscale operator access (`sudo tailscale set --operator="$USER"`)
to configure Serve without sudo. Keep Tailscale connected on client devices.

## Stop and update

```bash
cd ~/repos/homelab
podman compose stop learnharness
podman compose up -d learnharness
```

Before an upstream update, let background jobs finish, stop the app, and commit
the current data. Then rebase, build, and restart:

```bash
cd ~/repos/homelab
podman compose stop learnharness
cd ~/repos/learnharness
git add data
git commit -m "Back up learning data"  # skip if there are no changes
bash scripts/rebase-upstream.sh
# Review and run the push command printed by the script.
cd ~/repos/homelab
podman compose up -d --build learnharness
```

For consistent Git backups, also stop the app while committing data, then start
it again. A public fork makes committed session content publicly readable.
This server is the active data source; avoid writing to desktop copies.

## Nightly data backups

The backup script and systemd units are tracked in this repository:

- `scripts/backup-data.py`
- `deploy/homelab/learnharness-backup.service`
- `deploy/homelab/learnharness-backup.timer`

The timer runs nightly at **03:00 in the server's timezone** (America/Los_Angeles
on `cbox`). Missed runs are caught up after the machine starts again. If a session,
compaction, or background job is active, it defers and retries every 30 minutes.
Push failures also retry every 30 minutes; an already-created commit is retried
even if there are no newer data changes. Unchanged data creates no empty commits.
The installed service checks the app at `http://127.0.0.1:3000/learnharness`; copy
the updated service file and reload systemd after changing the app's URL prefix.

The app stays running. Two matching, idle snapshots are required, and JSON/JSONL
files must parse before committing. Only Git-trackable `data/` paths enter the
snapshot; the app's `.secrets/` directory stays local. A separate temporary Git
index keeps unrelated edits out of the backup. A shared lock prevents concurrent
backups and Linux runs of the upstream rebase helper. New remote commits or
diverged history require manual reconciliation: the script never pulls, rebases,
or force-pushes. Stop the backup timer and service before manual Git maintenance.

On `cbox`, view the last result, next scheduled run, and recent logs with:

```bash
cd ~/repos/learnharness
python3 scripts/backup-data.py --status
```

Run a backup now, follow logs, or pause scheduling:

```bash
systemctl --user start learnharness-backup.service
journalctl --user -u learnharness-backup.service -f
systemctl --user stop learnharness-backup.timer learnharness-backup.service
# Resume after maintenance:
systemctl --user start learnharness-backup.timer
```

To install on another server, configure this checkout's Git author identity and
unattended push authentication first, then install the units:

```bash
cp deploy/homelab/learnharness-backup.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now learnharness-backup.timer
```

On `cbox`, the origin fetch URL stays HTTPS and its push URL uses the server's
existing GitHub SSH key. The last attempt and last successful push are recorded
in `.git/learnharness-backup.json`, outside tracked data. Timer definitions are
in Git, but installing or editing them requires copying them into the systemd
user directory and running `systemctl --user daemon-reload`. To verify the backup
script with temporary local repositories and a mock API, run
`python3 tests/test_backup_data.py`.

## Restart after reboot

The Compose restart policy handles process exits. Install the supplied systemd
user unit for reboot recovery after the first image build succeeds:

```bash
sudo loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
cp ~/repos/learnharness/deploy/homelab/homelab.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now homelab.service
```

The unit uses `~/repos/homelab` and the `/usr/bin/podman-compose` provider. It
starts the entire shared stack at boot and stops it on user-service shutdown.
Use `systemctl --user stop homelab` to stop all apps, or `systemctl --user disable
homelab` to disable boot startup. Keep this unit as the stack's only systemd
supervisor. A reboot will start apps that were previously stopped individually
with Compose. Verify reboot recovery on your server when convenient.

References: [Podman Compose](https://docs.podman.io/en/latest/markdown/podman-compose.1.html),
[Podman restart service](https://docs.podman.io/en/latest/markdown/podman-restart.1.html),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
