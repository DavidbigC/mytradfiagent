1. On the OLD server — export everything                                                                                            
                                                                                                                                      
  Database dump:
  pg_dump myaiagent > /tmp/myaiagent_db.sql                                                                                           
                                                                             
  App files + env:
  tar -czf /tmp/myaiagent_app.tar.gz /mytradfiagent --exclude='/mytradfiagent/.venv'

  Service file:
  cp /etc/systemd/system/myaiagent.service /tmp/

  Nginx config:
  cp /etc/nginx/sites-available/myaiagent /tmp/

  SSL cert (optional — easier to just re-issue):
  tar -czf /tmp/letsencrypt.tar.gz /etc/letsencrypt

  2. Copy files to the NEW server

  scp /tmp/myaiagent_db.sql /tmp/myaiagent_app.tar.gz /tmp/myaiagent.service /tmp/myaiagent root@NEW_IP:/tmp/

  3. On the NEW server — set up

  Install dependencies:
  apt update && apt install -y python3 python3-pip postgresql nginx
  snap install --classic certbot

  Restore app:
  tar -xzf /tmp/myaiagent_app.tar.gz -C /
  cd /mytradfiagent
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt

  Restore database:
  sudo -u postgres createdb myaiagent
  sudo -u postgres psql myaiagent < /tmp/myaiagent_db.sql

  Service + nginx:
  cp /tmp/myaiagent.service /etc/systemd/system/
  cp /tmp/myaiagent /etc/nginx/sites-available/myaiagent
  ln -s /etc/nginx/sites-available/myaiagent /etc/nginx/sites-enabled/

  Update nginx config with the new server IP (if hardcoded anywhere), then:
  systemctl daemon-reload
  systemctl enable myaiagent
  systemctl start myaiagent
  nginx -t && systemctl start nginx

  Re-issue SSL cert (easiest — use DNS challenge again):
  certbot certonly --manual --preferred-challenges dns -d tradfiagentcn.xyz

  4. Switch DNS

  In GoDaddy, update the A record to point to the new server's IP. Wait for propagation (~5-15 min), then verify:
  curl https://tradfiagentcn.xyz/api/chat/active

  5. Decommission old server

  Only after confirming everything works on the new server.

  ---
  The critical things not to forget: .env file (all your API keys), the database dump, and any generated report files in the app
  directory.