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
# SVG 도형을 이미지로 변환하는 네이티브 라이브러리. 별도 이미지 API는 사용하지 않는다.
if ! ldconfig -p | grep 'libcairo.so.2' >/dev/null; then
  sudo dnf install -y cairo
fi

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
echo "=== 4b. intake worker ==="
UNIT_SRC="$REPO_DIR/scripts/hantijae-intake.service"
UNIT_DST="/etc/systemd/system/hantijae-intake.service"
if [ -f "$UNIT_DST" ]; then
  if ! cmp -s "$UNIT_SRC" "$UNIT_DST"; then
    sudo cp "$UNIT_SRC" "$UNIT_DST"
    sudo systemctl daemon-reload
  fi
  sudo systemctl restart hantijae-intake
  echo "(intake worker restarted)"
  sudo cp "$REPO_DIR/scripts/hantijae-visuals.service" /etc/systemd/system/hantijae-visuals.service
  sudo systemctl daemon-reload
  sudo systemctl enable hantijae-visuals
  sudo systemctl restart hantijae-visuals
else
  echo "(intake worker not installed — skip)"
fi

echo ""
echo "=== 5. nginx reload (config 변경 가능성) ==="
sudo nginx -t
sudo systemctl reload nginx
echo "(nginx reloaded)"

echo ""
echo "=== Deploy 완료 ==="
