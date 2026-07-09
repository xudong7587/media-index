# Security Policy

## Sensitive Files

Never commit these files or directories:

- .env
- data/
- database files such as *.db, *.sqlite, *.sqlite3
- logs
- private screenshots or task records

## Secrets

The following values are sensitive:

- QAS_TOKEN
- TMDB_API_KEY
- AUTH_SECRET
- NAS usernames, paths, hostnames, and private reverse-proxy domains

If any secret is accidentally committed or published, rotate it immediately.

## Deployment Advice

- Change the default password before first use. `MEDIA_PASS=admin` is refused by the application.
- Do not expose the service directly to the public internet.
- Prefer VPN, LAN-only deployment, or a reverse proxy with authentication.
- Restrict access to QAS and PanSou endpoints.
- Back up your database before upgrades.

## Reporting Issues

Do not include tokens, cookies, private links, or personal NAS paths in public issues. Redact all sensitive values before sharing logs.
