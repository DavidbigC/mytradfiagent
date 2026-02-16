#!/usr/bin/env bash
# Server setup script for Ubuntu 22.04/24.04
# Run as root: bash deploy.sh
set -euo pipefail

APP_USER="myaiagent"
APP_DIR="/opt/myaiagent"
REPO_URL="${1:-}"

echo "=== Financial Research Agent — Server Setup ==="

# 1. System packages
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nodejs npm postgresql postgresql-contrib \
    libpq-dev build-essential curl git fonts-noto-cjk > /dev/null

# 2. PostgreSQL setup
echo "[2/7] Setting up PostgreSQL..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='myaiagent'" | grep -q 1 || \
    sudo -u postgres createuser myaiagent
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='myaiagent'" | grep -q 1 || \
    sudo -u postgres createdb -O myaiagent myaiagent
sudo -u postgres psql -c "ALTER USER myaiagent PASSWORD 'changeme';" > /dev/null
echo "  PostgreSQL ready (user: myaiagent, db: myaiagent)"
echo "  ** Change the password: sudo -u postgres psql -c \"ALTER USER myaiagent PASSWORD 'yourpassword';\""

# 3. App user & directory
echo "[3/7] Creating app user and directory..."
id -u $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER
mkdir -p $APP_DIR
if [ -n "$REPO_URL" ]; then
    echo "  Cloning from $REPO_URL..."
    if [ -d "$APP_DIR/.git" ]; then
        cd $APP_DIR && git pull
    else
        git clone "$REPO_URL" $APP_DIR
    fi
else
    echo "  No repo URL provided. Copy your code to $APP_DIR manually."
    echo "  Usage: bash deploy.sh https://github.com/youruser/myaiagent.git"
fi
chown -R $APP_USER:$APP_USER $APP_DIR

# 4. Python environment
echo "[4/7] Setting up Python environment..."
sudo -u $APP_USER bash -c "cd $APP_DIR && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt"

# 5. Frontend build
echo "[5/7] Building frontend..."
sudo -u $APP_USER bash -c "cd $APP_DIR/frontend && npm install --silent && npm run build"

# 6. Environment file
echo "[6/7] Setting up .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    # Set a random JWT secret
    JWT=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/change-this-to-a-random-string/$JWT/" "$APP_DIR/.env"
    sed -i "s/yourpassword/changeme/" "$APP_DIR/.env"
    chown $APP_USER:$APP_USER "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo "  Created .env — edit it now: nano $APP_DIR/.env"
else
    echo "  .env already exists, skipping"
fi

# 7. Systemd service
echo "[7/7] Creating systemd service..."
cat > /etc/systemd/system/myaiagent.service << 'EOF'
[Unit]
Description=Financial Research Agent
After=network.target postgresql.service

[Service]
Type=simple
User=myaiagent
WorkingDirectory=/opt/myaiagent
ExecStart=/opt/myaiagent/.venv/bin/python start.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/myaiagent/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable myaiagent

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit your config:     nano $APP_DIR/.env"
echo "  2. Set DB password:      sudo -u postgres psql -c \"ALTER USER myaiagent PASSWORD 'yourpassword';\""
echo "  3. Start the app:        systemctl start myaiagent"
echo "  4. Check status:         systemctl status myaiagent"
echo "  5. View logs:            journalctl -u myaiagent -f"
echo ""
echo "The app will run on port 8000. Access it at http://YOUR_SERVER_IP:8000"
