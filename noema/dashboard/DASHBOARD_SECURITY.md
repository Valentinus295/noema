# Dashboard Security

## Overview

The Noema Dashboard API server serves trading data, agent status, and account metrics via REST and WebSocket. This document explains how to secure it for production.

## Quick Start: Development

For local development, auth is **disabled by default** (no `DASHBOARD_API_KEY` set). The CORS policy allows:
- `http://localhost:3000` (React dev server)
- `http://localhost:5173` (Vite dev server)
- `http://localhost:8000`

No credentials needed.

## Production Setup

### 1. Set the API Key

```bash
# Generate a strong random key
openssl rand -hex 32
# → a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2

# Set it as an environment variable
export DASHBOARD_API_KEY="your-generated-key"
```

Once set, **all `/api/*` endpoints and WebSocket connections require authentication**.

### 2. REST API Authentication

Clients must provide the API key via one of:

**Authorization Header (recommended):**
```bash
curl -H "Authorization: Bearer YOUR_KEY" http://dashboard:8000/api/status
```

**Query Parameter:**
```bash
curl "http://dashboard:8000/api/status?token=YOUR_KEY"
```

### 3. WebSocket Authentication

```javascript
const ws = new WebSocket(`ws://dashboard:8000/ws?token=YOUR_KEY`);
```

### 4. CORS Configuration

In production, update `dashboard/server/api.py` to restrict `allow_origins` to your actual dashboard domain:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dashboard.your-domain.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 5. HTTPS / TLS

Always run behind a reverse proxy (nginx, Caddy) with TLS in production:

```nginx
server {
    listen 443 ssl;
    server_name dashboard.your-domain.com;

    ssl_certificate /etc/letsencrypt/live/dashboard/cert.pem;
    ssl_certificate_key /etc/letsencrypt/live/dashboard/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 6. Rate Limiting

Built-in token bucket rate limiter (120 requests/minute, burst 200). Adjust in `api.py` if needed:

```python
rate_limiter = TokenBucket(rate=120, burst=200)
```

### 7. Deploy Checklist

- [ ] Set `DASHBOARD_API_KEY` environment variable (strong random key)
- [ ] Update CORS to production domain
- [ ] Run behind nginx/Caddy with TLS
- [ ] Firewall: only expose dashboard port (8000) to reverse proxy, not public
- [ ] Test auth with `curl -I -H "Authorization: Bearer $KEY" http://localhost:8000/api/status` → 200
- [ ] Test unauthenticated with `curl -I http://localhost:8000/api/status` → 401
- [ ] Test WebSocket auth with wscat or browser

### 8. Disabling Auth (Not Recommended)

If you must disable auth (e.g., in fully isolated environments):

```bash
export DASHBOARD_SKIP_AUTH=1
```

This should only be used in development or air-gapped networks.

## Security Model Summary

| Component | Protection |
|-----------|-----------|
| REST `/api/*` | API key via `Authorization: Bearer` header or `?token=` query param |
| WebSocket `/ws` | API key via `?token=` query param |
| CORS | Restricted to configured origins (localhost in dev) |
| Rate Limiting | Token bucket: 120 req/min, burst 200 |
| Static files | No auth required (serves the React SPA) |
