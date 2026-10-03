"""텔레그램 수신(getUpdates) 끊김 기록의 키 이름과 기준. 워커(intake.pipeline)가 적고 상태 페이지(ops.health)가 읽는다.
웹 프로세스가 pipeline(문서 파서·마케팅 작업 전체)을 불러오지 않게 따로 둔다."""

TG_ALERT_AFTER = 3   # 한두 번 끊김은 다음 바퀴에 저절로 회복된다(10-01·10-02 확인) — 연속 이만큼일 때만 알린다
OUTAGE = 'telegram_poll_outage'            # 지금 끊김: {since, fails, alerted, error}, 연결되면 None
LAST_OUTAGE = 'telegram_poll_last_outage'  # 끝난 마지막 끊김: {since, until, fails, error}
