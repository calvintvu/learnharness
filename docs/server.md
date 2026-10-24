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
curl --fail http://127.0.0.1:3000/api/settings
```

To access it initially from your laptop or desktop, keep this SSH tunnel open
and visit `http://localhost:3000`:

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
tailscale serve --bg http://127.0.0.1:3000
tailscale serve status
```

Follow any HTTPS setup link Tailscale prints. Open the resulting
`https://cbox.<your-tailnet>.ts.net` address from a device connected to your
tailnet, at home or away. Use the actual URL printed by Tailscale. HTTPS also
allows browser microphone access for dictation. Keep access limited to your
devices using your tailnet policy; LearnHarness does not provide a user-login
boundary. If this server already has Serve routes, inspect `tailscale serve
status` before changing them. This command configures the default HTTPS route.
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
