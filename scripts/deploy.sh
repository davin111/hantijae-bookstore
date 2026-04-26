#!/bin/bash
# hantijae-bookstore Lightsail 배포 스크립트
# 호출: ssh hantijae-prod 'bash ~/hantijae-bookstore/scripts/deploy.sh'
# 또는 GitHub Actions가 자동 호출 (main push → .github/workflows/deploy.yml)

set -euo pipefail

REPO_DIR="/home/ec2-user/hantijae-bookstore"
VENV="/home/ec2-user/.pyenv/versions/hantijae-bookstore"

cd "$REPO_DIR"

echo "=== 1. git pull origin main ==="
git fetch origin main
git reset --hard origin/main
git log --oneline -1

echo ""
echo "=== 2. Python deps (venv) ==="
"$VENV/bin/pip" install -q -r django/requirements.txt

echo ""
echo "=== 3. Django migrate + collectstatic ==="
cd django/hantijae_bookstore
MODE=prod "$VENV/bin/python" manage.py migrate --noinput
echo yes | MODE=prod "$VENV/bin/python" manage.py collectstatic --noinput | tail -3

echo ""
echo "=== 4. uWSGI graceful reload ==="
# lazy-apps=true + master mode이라 SIGHUP만으로 worker 교체 (제로 다운타임)
sudo systemctl reload hantijae-uwsgi
echo "(uwsgi reloaded)"

echo ""
echo "=== 5. nginx reload (config 변경 가능성) ==="
sudo nginx -t
sudo systemctl reload nginx
echo "(nginx reloaded)"

echo ""
echo "=== Deploy 완료 ==="
