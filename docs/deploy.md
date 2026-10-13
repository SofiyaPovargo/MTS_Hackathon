# Deploy (server side)

The MVP server side runs as the same Docker Compose stack as development, on a
VPS, with real TLS and secrets from `.env`. Track C, item 6 of `TEAM_PLAN.md`.
The mobile app is not containerized; it points at the deployed host via build
configuration (`MEDIA_INGEST_URL` / backend URL), not a hardcoded address.

## 1. Prerequisites

- A VPS with Docker Engine and the Compose plugin
  (`docker compose version`).
- A DNS `A`/`AAAA` record for the host (e.g. `app.example.com`) pointing at it.
- Ports `80` and `443` open. Everything else stays closed.

## 2. Configure secrets

```bash
git clone <repo> && cd MTS_Hackathon
cp .env.example .env
```

Edit `.env` (never commit it). The values that **must** change for production:

| variable | value |
| --- | --- |
| `APP_ENV` | `production` |
| `PUBLIC_HOSTNAME` | the DNS name the certificate is issued for |
| `PUBLIC_BASE_URL` | `https://<PUBLIC_HOSTNAME>` (Exolve callbacks) |
| `MEDIA_INGEST_URL` | `https://<PUBLIC_HOSTNAME>/api` (mobile audio upload) |
| `JWT_SECRET` | long random string |
| `DATA_ENCRYPTION_KEY` | long random string — **set once, never rotate** (data written with it cannot be read with another) |
| `VOICE_WEBHOOK_SECRET` | long random string (fits in the Exolve callback URL) |
| `VOICE_PROVIDER` | `exolve` |
| `EXOLVE_API_KEY` | Exolve API key |
| `EXOLVE_SIP_RESOURCE_ID`, `EXOLVE_CONSENT_NOTICE_FILE_ID`, `EXOLVE_SIP_ROUTES` | from the Exolve SIP resource |
| `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | strong values |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | the self-hosted LLM endpoint |
| `DEV_OTP` | **empty** (the fixed OTP must never work in production) |

`PUBLIC_BASE_URL` is required: Exolve must be able to reach the call-control and
event callbacks. Register these URLs in Exolve (note the shared secret in the
query string, because Exolve does not set signature headers):

- call-control: `https://<host>/api/voice/exolve/control?secret=<VOICE_WEBHOOK_SECRET>`
- events: `https://<host>/api/voice/exolve/events?secret=<VOICE_WEBHOOK_SECRET>`

## 3. TLS with Let's Encrypt

Issue the certificate on the host with certbot in standalone mode (nginx must
not hold port 80 yet):

```bash
sudo apt-get install -y certbot
sudo certbot certonly --standalone -d "$PUBLIC_HOSTNAME" --agree-tos -m ops@example.com
```

`docker-compose.prod.yml` mounts
`/etc/letsencrypt/live/$PUBLIC_HOSTNAME/{fullchain.pem,privkey.pem}` into nginx.
Renewal (certificates last 90 days):

```bash
sudo certbot renew --deploy-hook "docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx"
```

## 4. Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Do **not** include `docker-compose.override.yml`: the dev file publishes
`postgres`, `redis`, `minio` and `ollama` to the host. With only the base +
prod files, nginx is the single published service.

What happens:

1. `postgres`, `redis`, `minio` start and become healthy;
2. the one-off `migrate` service runs `alembic upgrade head` (never on API
   startup, never from several containers);
3. `api`, the workers and `beat` start; nginx serves 80 → 443 and proxies
   WebSocket.

Migrations add AES-encrypted columns (see `services/api/README.md`); the first
boot on an existing database keeps legacy plain rows readable.

## 5. Verify

```bash
curl -fsS https://$PUBLIC_HOSTNAME/api/ws/events/schema >/dev/null && echo "api ok"
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

- `GET https://<host>/docs` — OpenAPI.
- `GET https://<host>/api/ws/events/schema` — the WebSocket event contract.
- Log in with a real phone (OTP is no longer `1234`).

## 6. Operations

- **Backups**: `pg_dump` for PostgreSQL, and the `minio_data` volume for audio
  objects. The phone's local database is only a cache; the server is the source
  of truth.
- **Retention**: `beat` purges audio past `AUDIO_RETENTION_DAYS` daily (03:00 UTC).
- **Deletion**: `POST /api/me/data/delete` removes a user's audio, calls,
  transcripts, agreements and tasks; consent history and `audit_log` remain.
- **Logs**: never contain raw audio, transcripts or prompts. `DATA_ENCRYPTION_KEY`
  loss is unrecoverable — keep it with the other secrets.
