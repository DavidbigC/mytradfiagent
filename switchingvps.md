# Server Deployment Guide

Remote server: `tradfiagentcn.xyz` — Ubuntu/Debian VPS, Nginx reverse proxy, systemd service, Let's Encrypt SSL.

---

## 1. Fresh Server Setup

### Install system packages

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib nginx git
snap install --classic certbot
```

### Create app directory and clone

```bash
git clone <your-repo-url> /myaiagent
cd /myaiagent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Node.js (for frontend build)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
```

---

## 2. Environment Variables

Create `/myaiagent/.env`:

```env
# ── Primary LLM — MiniMax ──────────────────────────────────────────────────
# Provider: "fireworks" (default) or "minimax" (official API)
MINIMAX_PROVIDER=fireworks
FIREWORKS_API_KEY=fw_...
FIREWORKS_MINIMAX_MODEL=accounts/fireworks/models/minimax-m2p1

# Official MiniMax fallback (set MINIMAX_PROVIDER=minimax to use)
MINIMAX_API_KEY=...
MINIMAX_BASE_URL=https://api.minimaxi.chat/v1
MINIMAX_MODEL=MiniMax-M1-80k

# ── Debate bear analysts ───────────────────────────────────────────────────
QWEN_API_KEY=...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# ── Web search + report reading ────────────────────────────────────────────
GROK_API_KEY=...
GROK_BASE_URL=https://api.x.ai/v1
GROK_MODEL_noreasoning=grok-4-1-fast-non-reasoning

# ── Groq (PDF summarization) ───────────────────────────────────────────────
GROQ_API_KEY=...
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_REPORT_MODEL=openai/gpt-oss-20b

# ── Speech-to-text ─────────────────────────────────────────────────────────
OPENAI_API_KEY=...

# ── Databases ──────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/myaiagent
MARKETDATA_URL=postgresql://postgres:yourpassword@localhost:5432/marketdata

# ── App ────────────────────────────────────────────────────────────────────
JWT_SECRET=change-this-to-a-long-random-string
WEB_PORT=8000
ADMIN_USERNAME=davidc
```

---

## 3. Database Setup

### Create databases

```bash
sudo -u postgres psql -c "CREATE DATABASE myaiagent;"
sudo -u postgres psql -c "CREATE DATABASE marketdata;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'yourpassword';"
```

### Initialize main app schema

The schema is auto-created on first startup via `init_db()` in `db.py`. Just start the app once.

### Initialize market data schema + ingest

```bash
# Create ohlcv_5m table and indexes
.venv/bin/python data/setup_db.py

# Bulk historical ingest — takes 2–4 hours, run in tmux
tmux new -s ingest
.venv/bin/python data/ingest_ohlcv.py
# Ctrl+B then D to detach
```

See `data/SETUP.md` for full details on the market data pipeline.

---

## 4. Admin Account

Create the admin user before first login:

```bash
cd /myaiagent
.venv/bin/python create_admin.py
```

---

## 5. systemd Service

Create `/etc/systemd/system/myaiagent.service`:

```ini
[Unit]
Description=MyAIAgent Financial Research Assistant
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/myaiagent
EnvironmentFile=/myaiagent/.env
ExecStart=/myaiagent/.venv/bin/python start.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable myaiagent
systemctl start myaiagent
systemctl status myaiagent
```

Logs:
```bash
journalctl -u myaiagent -f
```

---

## 6. Nginx + SSL

### Nginx config

Create `/etc/nginx/sites-available/myaiagent`:

```nginx
server {
    listen 80;
    server_name tradfiagentcn.xyz;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name tradfiagentcn.xyz;

    ssl_certificate     /etc/letsencrypt/live/tradfiagentcn.xyz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tradfiagentcn.xyz/privkey.pem;

    # SSE: disable buffering so events stream through immediately
    proxy_buffering off;
    proxy_cache off;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE / long-running requests
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

```bash
ln -s /etc/nginx/sites-available/myaiagent /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx
```

### SSL certificate (DNS challenge — works without port 80 open)

```bash
certbot certonly --manual --preferred-challenges dns -d tradfiagentcn.xyz
```

Follow the prompts: add the TXT record in GoDaddy DNS, wait ~1 min, then press Enter.

Auto-renewal:
```bash
echo "0 3 * * * certbot renew --quiet && systemctl reload nginx" | crontab -
```

---

## 7. Cron Jobs

```bash
crontab -e
```

```cron
# OHLCV daily update — runs after A-share market close (16:30 CST = 08:30 UTC)
30 8 * * 1-5 cd /myaiagent && .venv/bin/python data/update_ohlcv.py >> /var/log/ohlcv_update.log 2>&1

# SSL auto-renewal
0 3 * * * certbot renew --quiet && systemctl reload nginx
```

---

## 8. Firewall

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw enable
```

---

## 9. Verify Everything Works

```bash
# App health
curl https://tradfiagentcn.xyz/api/chat/active

# Check service
systemctl status myaiagent

# Check DB connections
.venv/bin/python -c "import asyncio; from db import init_db; asyncio.run(init_db())"
```

---

## 10. Updating the App

```bash
cd /myaiagent
git pull
.venv/bin/pip install -r requirements.txt   # if dependencies changed
systemctl restart myaiagent                 # start.py auto-rebuilds frontend on restart
```

---

## 11. Migrating to a New Server

### On the OLD server — export everything

```bash
# Database
pg_dump myaiagent > /tmp/myaiagent_db.sql
pg_dump marketdata > /tmp/marketdata_db.sql

# App files + env (exclude venv and frontend build)
tar -czf /tmp/myaiagent_app.tar.gz /myaiagent \
    --exclude='/myaiagent/.venv' \
    --exclude='/myaiagent/frontend/node_modules' \
    --exclude='/myaiagent/frontend/dist'

# Service + nginx config
cp /etc/systemd/system/myaiagent.service /tmp/
cp /etc/nginx/sites-available/myaiagent /tmp/myaiagent_nginx

# Generated output files (PDFs, charts)
tar -czf /tmp/myaiagent_output.tar.gz /myaiagent/output/
```

### Copy to new server

```bash
scp /tmp/myaiagent_db.sql /tmp/marketdata_db.sql \
    /tmp/myaiagent_app.tar.gz /tmp/myaiagent_output.tar.gz \
    /tmp/myaiagent.service /tmp/myaiagent_nginx \
    root@NEW_IP:/tmp/
```

### On the NEW server — restore

```bash
# App
tar -xzf /tmp/myaiagent_app.tar.gz -C /
cd /myaiagent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Output files
tar -xzf /tmp/myaiagent_output.tar.gz -C /

# Databases
sudo -u postgres createdb myaiagent
sudo -u postgres createdb marketdata
sudo -u postgres psql myaiagent < /tmp/myaiagent_db.sql
sudo -u postgres psql marketdata < /tmp/marketdata_db.sql

# Service + nginx
cp /tmp/myaiagent.service /etc/systemd/system/
cp /tmp/myaiagent_nginx /etc/nginx/sites-available/myaiagent
ln -s /etc/nginx/sites-available/myaiagent /etc/nginx/sites-enabled/
systemctl daemon-reload
systemctl enable myaiagent
systemctl start myaiagent
nginx -t && systemctl start nginx

# Re-issue SSL cert
certbot certonly --manual --preferred-challenges dns -d tradfiagentcn.xyz
```

### Switch DNS

In GoDaddy, update the A record to the new server IP. Wait ~5–15 min, then verify:

```bash
curl https://tradfiagentcn.xyz/api/chat/active
```

> **Don't forget:** `.env` file (API keys), both database dumps, and `output/` directory.
