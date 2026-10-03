#!/usr/bin/env python3
"""광고 성과 토큰 갱신(Mac에서 실행, Django 없음). 스펙 .claude/docs/specs/2026-10-03-ads-collector-design.md §7.1(로컬).

  python scripts/meta_ads_token.py --token-file PATH [--account act_…] [--check] [--no-restart]

탐색기에서 받은 짧은 토큰 → 60일 토큰 교환 → debug_token 확인(유효·ads_read·만료일) → 광고 계정 읽기 확인
→ Secrets Manager에 META_ADS_TOKEN·META_AD_ACCOUNT_ID·META_ADS_EXPIRES 병합 저장 → 서버 워커 재시작·uWSGI reload.
settings.py는 Secrets를 프로세스가 뜰 때 한 번만 읽어서, 재시작하지 않으면 워커가 옛 토큰을 계속 쓴다.
토큰 값은 어디에도 출력하지 않는다. 토큰 파일은 성공·실패와 상관없이 마지막에 지운다."""
import argparse
import hashlib
import hmac
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

GRAPH = 'https://graph.facebook.com/v26.0'
SECRET_ID, REGION = 'prod/hantijae-bookstore', 'ap-northeast-2'
KST = timezone(timedelta(hours=9))
DAWN = ((4, 30), (7, 10))   # 새벽 수집(서평 04:30 ~ 광고 06:50) 중에는 워커를 재시작하지 않는다
RESTART = 'sudo systemctl restart hantijae-intake && sudo systemctl reload hantijae-uwsgi'


class Stop(Exception):
    pass


def in_dawn(now):
    local = now.astimezone(KST)
    return DAWN[0] <= (local.hour, local.minute) < DAWN[1]


def expiry_date(info):
    """토큰 만료와 데이터 접근 만료 가운데 이른 날(KST). 0은 '만료 없음'이라 뺀다."""
    stamps = [info.get(k) for k in ('expires_at', 'data_access_expires_at') if info.get(k)]
    if not stamps:
        raise Stop('debug_token에 만료일이 없어요')
    return datetime.fromtimestamp(min(stamps), KST).date()


def proof(token, secret):
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def graph(get, path, params, label):
    """label은 오류 문구용 이름(주소에 광고 계정 번호가 들어 있어서 그대로 보이지 않게)."""
    try:
        res = get(f'{GRAPH}/{path}', params=params, timeout=20)
    except requests.RequestException as e:
        # 예외 문구에는 토큰이 든 주소가 들어갈 수 있어, 종류 이름만 남기고 원인 연결도 끊는다
        raise Stop(f'{label}: {type(e).__name__}') from None
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code >= 400:
        code = (body.get('error') or {}).get('code') if isinstance(body, dict) else None
        raise Stop(f'{label}: HTTP {res.status_code}' + (f' code {code}' if code else ''))
    return body


def exchange(get, app_id, secret, short):
    return graph(get, 'oauth/access_token', {'grant_type': 'fb_exchange_token', 'client_id': app_id,
                                             'client_secret': secret, 'fb_exchange_token': short}, '토큰 교환')['access_token']


def debug(get, app_id, secret, token):
    app_token = f'{app_id}|{secret}'
    info = graph(get, 'debug_token', {'input_token': token, 'access_token': app_token,
                                      'appsecret_proof': proof(app_token, secret)}, '토큰 확인').get('data') or {}
    if not info.get('is_valid') or str(info.get('app_id')) != str(app_id):
        raise Stop('토큰이 유효하지 않거나 다른 앱의 토큰이에요')
    if 'ads_read' not in (info.get('scopes') or []):
        raise Stop('토큰에 ads_read 권한이 없어요 — 탐색기에서 권한을 확인해 주세요')
    return info


def verify_account(get, token, secret, account):
    return graph(get, account, {'fields': 'id,currency,timezone_name', 'access_token': token,
                                'appsecret_proof': proof(token, secret)}, '광고 계정')


def parse(argv):
    ap = argparse.ArgumentParser(description='광고 성과 토큰 갱신', allow_abbrev=False)   # 줄임말 오타가 조용히 통하지 않게
    ap.add_argument('--token-file', required=True)
    ap.add_argument('--account', help='광고 계정(act_…). 처음 한 번만, 그 뒤에는 Secrets 값을 쓴다')
    ap.add_argument('--check', action='store_true', help='확인만 하고 저장하지 않는다')
    ap.add_argument('--no-restart', action='store_true', help='저장만 하고 서버를 재시작하지 않는다')
    return ap.parse_args(argv)


def main(argv=None, get=requests.get, sm=None, run=subprocess.run, now=None):
    # 토큰 파일 경로만 먼저 읽는다 — 옵션 오타나 --help로 끝나도 파일은 지워야 해서(argparse는 SystemExit로 끝낸다)
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument('--token-file')
    known, _ = pre.parse_known_args(argv)
    path = Path(known.token_file) if known.token_file else None
    try:
        args = parse(argv)
        if not args.check and not args.no_restart and in_dawn(now or datetime.now(timezone.utc)):
            raise Stop('새벽 수집 시간(04:30~07:10 KST)이에요. 끝난 뒤에 다시 돌려 주세요')
        short = path.read_text().strip()
        if not short:
            raise Stop('토큰 파일이 비었어요')
        if sm is None:
            import boto3
            sm = boto3.client('secretsmanager', region_name=REGION)
        current = sm.get_secret_value(SecretId=SECRET_ID)
        data = json.loads(current['SecretString'])
        app_id, secret = data['META_APP_ID'], data['META_APP_SECRET']
        account = args.account or data.get('META_AD_ACCOUNT_ID')
        if not account:
            raise Stop('광고 계정 번호가 없어요 — 처음에는 --account act_… 로 주세요')
        token = exchange(get, app_id, secret, short)
        info = debug(get, app_id, secret, token)
        expires = expiry_date(info)
        acct = verify_account(get, token, secret, account)
        print(f"권한 {len(info.get('scopes') or [])}개: {', '.join(sorted(info.get('scopes') or []))}")
        print(f"광고 계정 확인: 통화 {acct.get('currency')}, 시간대 {acct.get('timezone_name')}")
        print(f'만료일(토큰·데이터 접근 가운데 이른 날): {expires.isoformat()}')
        if args.check:
            print('--check: 저장하지 않았어요')
            return 0
        merged = {**data, 'META_ADS_TOKEN': token, 'META_AD_ACCOUNT_ID': account, 'META_ADS_EXPIRES': expires.isoformat()}
        result = sm.put_secret_value(SecretId=SECRET_ID, SecretString=json.dumps(merged, ensure_ascii=False))
        print(f"저장됨. 새 버전 {result['VersionId']}, 되돌릴 때 쓸 이전 버전 {current['VersionId']}")
        if not args.no_restart:
            try:
                run(['ssh', 'hantijae-prod', RESTART], check=True)
            except (subprocess.CalledProcessError, OSError):
                print('새 토큰은 이미 저장됐어요(위 버전 번호). 하지만 서버 재시작에 실패했어요. '
                      f"직접 재시작해 주세요: ssh hantijae-prod '{RESTART}'", file=sys.stderr)
                return 1
            print('서버 워커 재시작·uWSGI reload 완료')
        return 0
    except Stop as e:
        print(f'멈춤: {e}', file=sys.stderr)
        return 1
    finally:
        if path is not None and path.exists():
            path.unlink()


if __name__ == '__main__':
    sys.exit(main())
