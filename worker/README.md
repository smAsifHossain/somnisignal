# Cloudflare Worker proxy

This is the only browser-facing backend. It restricts CORS to the GitHub Pages
origin, verifies Turnstile, enforces an exact three-POSTs-per-hashed-IP hourly
limit with a Durable Object, strips incoming identifying headers, and injects the
secret laptop API bearer token. A second Durable Object maintains a public aggregate
of completed screenings and briefly remembers random job IDs to prevent duplicate
counting. It stores no ECG data, prediction, filename, IP address, or user identity.

Before deployment, edit `wrangler.toml`, create a Turnstile widget for the Pages
origin, and set all three secrets listed in that file. Never place the laptop API
token in `frontend/config.js`.

The tunnel endpoint must require authenticated HTTPS access from this Worker.
Do not expose laptop port 8000 directly to the internet.
