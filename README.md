# Media Index

Media Index is a self-hosted media automation console for personal NAS workflows. It combines TMDB metadata, PanSou search, and quark-auto-save (QAS) task triggering to help manage discovery, wishlists, and transfer workflows.

> This project does not provide media resources, download links, cookies, accounts, or any copyrighted content. You must provide your own third-party service configuration.

## Features

- TMDB discovery poster flow for movies, TV, and variety shows
- Server-side TMDB caching to reduce API usage
- PanSou-based quick resource availability checks
- QAS integration for cloud transfer workflows
- Smart tracking task records for ongoing shows
- Wishlist page for unavailable or unsafe-to-transfer items
- Light/dark theme UI
- Docker deployment

## Required Services

You need to prepare these services yourself:

- TMDB API key
- PanSou service
- QAS service: https://github.com/Cp0204/quark-auto-save

## Quick Start With Docker Compose

Create a deployment directory and download the example files:

`ash
mkdir media-index
cd media-index
curl -o docker-compose.yml https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/media-index/main/docker-compose.example.yml
curl -o .env https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/media-index/main/.env.example
`

Edit .env and fill in your own values:

`env
TMDB_API_KEY=your_tmdb_key
QAS_BASE_URL=http://your-qas-host:25005
QAS_TOKEN=your_qas_token
PANSOU_URL=http://your-pansou-host:38111
MEDIA_PASS=change_this_password
AUTH_SECRET=change_this_to_a_long_random_string
`

Start the service:

`ash
docker compose up -d
`

Open:

`	ext
http://your-host:38000
`

## Build Locally

`ash
docker build -t media-index:local .
`

## Configuration

| Name | Description |
| --- | --- |
| MEDIA_USER / MEDIA_PASS | Login credentials for Media Index |
| AUTH_SECRET | Cookie signing secret, must be changed |
| TMDB_API_KEY | TMDB API key |
| QAS_BASE_URL | QAS base URL |
| QAS_TOKEN | QAS API token |
| PANSOU_URL | PanSou base URL |
| CLOUD_SAVE_PATH | Cloud/STRM root path, default /strm |
| LOCAL_SAVE_PATH | Local save root path |
| CATEGORY_PATHS_JSON | Category path mapping |
| WISHLIST_CRON_ENABLED | Wishlist scan switch |
| WISHLIST_CRON_SCHEDULE | Wishlist scan cron expression placeholder |

## Security Notes

- Do not upload .env to GitHub.
- Do not expose Media Index directly to the public internet.
- Put it behind VPN, private network, or a trusted reverse proxy with access control.
- QAS tokens can control your transfer tasks. Treat them like passwords.
- The local database may contain media titles, paths, and task records.

## Current Limitations

- Resource availability checks are intentionally fast and shallow.
- QAS execution is conservative: items that cannot be safely matched should go to wishlist or review instead of broad automatic transfer.
- Wishlist cron settings are configuration fields; production scheduling behavior should be reviewed for your own deployment.

## Container Image

Public images are intended to be published to GitHub Container Registry:

`ash
docker pull ghcr.io/YOUR_GITHUB_USERNAME/media-index:latest
`

Use versioned tags for stable deployments when available.

## Disclaimer

See [DISCLAIMER.md](DISCLAIMER.md).
