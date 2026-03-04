# Pixel Canvas — Cloud-Native & Serverless

Collaborative pixel drawing platform inspired by Reddit's r/place.
Built with AWS serverless services only.

## Architecture

- **API Gateway** — Single entry point for all public traffic
- **Lambda** — 6 functions following Single Responsibility Principle
- **SQS FIFO** — Event-driven async processing (2 queues)
- **DynamoDB** — Infinite canvas via chunk partitioning
- **S3** — Static frontend + PNG snapshots
- **Secrets Manager** — All secrets stored securely

## Lambda Functions

| Function | Trigger | Responsibility |
|---|---|---|
| `discord-proxy-fn` | API GW POST /discord/interactions | Verify Discord signature, ACK, publish to SQS |
| `pixel-worker-fn` | SQS pixel-events | Rate limit, session check, write pixel |
| `canvas-reader-fn` | API GW GET /canvas | Read canvas state from DynamoDB |
| `snapshot-worker-fn` | SQS snapshot-events | Generate PNG, upload S3, post Discord |
| `auth-fn` | API GW GET /auth/* | Discord OAuth2, JWT generation |
| `web-proxy-fn` | API GW POST /pixels | Authenticate web requests, publish to SQS |

## Data Model

### canvas-pixels
- PK: `CHUNK#cx#cy` (100x100 chunks → infinite canvas)
- SK: `PIXEL#x#y`

### rate-limits
- PK: `RATELIMIT#user_id` / SK: `WINDOW#minute`
- TTL: auto-expire after 2 minutes

### sessions
- PK: `SESSION#CURRENT` / SK: `METADATA`

## Deploy
```bash
sam build --use-container
sam deploy
python3 register_command.py
```

## Discord Commands
- `/draw x y color` — Draw a pixel
- `/canvas` — Post a snapshot
- `/session start|pause|reset` — Manage session