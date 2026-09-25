#!/bin/bash
# Secrets Manager prod/hantijae-bookstore 에 키 하나를 병합 저장한다. 값은 화면·argv에 남기지 않는다.
#   scripts/intake-set-secret.sh KEY              # 숨김 입력
#   scripts/intake-set-secret.sh KEY --file PATH  # 파일 내용 (서비스 계정 JSON 등)
#   scripts/intake-set-secret.sh KEY --random     # 난수 (초대 코드)
#   scripts/intake-set-secret.sh KEY --value V    # 비밀이 아닌 값 (URL, ID)
set -euo pipefail
KEY="$1"; OPT="${2:-}"
SECRET_ID="prod/hantijae-bookstore"; REGION="ap-northeast-2"
case "$OPT" in
  --file) VALUE="$(cat "$3")" ;;
  --random) VALUE="$(openssl rand -hex 12)" ;;
  --value) VALUE="$3" ;;
  "") read -r -s -p "$KEY 값 입력: " VALUE; echo ;;
  *) echo "알 수 없는 옵션: $OPT" >&2; exit 1 ;;
esac
umask 077
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ID" --query SecretString --output text > "$TMP"
KEY="$KEY" VALUE="$VALUE" python3 - "$TMP" <<'EOF'
import json, os, sys
path = sys.argv[1]
data = json.load(open(path))
data[os.environ['KEY']] = os.environ['VALUE']
json.dump(data, open(path, 'w'))
print('저장할 키 목록:', ', '.join(sorted(data)))
EOF
aws secretsmanager put-secret-value --region "$REGION" --secret-id "$SECRET_ID" --secret-string "file://$TMP" > /dev/null
echo "✔ $KEY 저장 완료"
