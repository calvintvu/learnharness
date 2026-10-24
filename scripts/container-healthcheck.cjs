// Keep the Compose command simple for older podman-compose shell quoting.
fetch(`http://127.0.0.1:3000${process.env.NEXT_PUBLIC_BASE_PATH || ""}/api/settings`, {
  signal: AbortSignal.timeout(5000),
})
  .then((response) => process.exit(response.ok ? 0 : 1))
  .catch(() => process.exit(1));
