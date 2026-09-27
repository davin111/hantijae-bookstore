import React, { Component } from 'react';
import { RouteComponentProps } from 'react-router-dom';

const KEY = 'hantijae:leave-spa';
const RETRY_WINDOW_MS = 10000;
const WINDOW_NAME_PREFIX = 'hantijae:leave-spa:';

interface State {
  stuck: boolean;
}

interface Mark {
  target: string;
  at: number;
}

// sessionStorage를 못 쓰는 환경(프라이빗 모드 등)에서는 window.name으로 대신 기억한다 —
// window.name은 같은 탭에서 페이지를 새로 불러와도(전체 페이지 이동) 유지된다.
function readWindowNameMark(): Mark | null {
  try {
    if (window.name.startsWith(WINDOW_NAME_PREFIX)) {
      return JSON.parse(window.name.slice(WINDOW_NAME_PREFIX.length));
    }
  } catch (e) {
    return null;
  }
  return null;
}

// sessionStorage에 쓸 수 있는 표시가 없으면(못 읽거나, 비어 있거나, 깨져 있으면) window.name도 본다 —
// setItem만 막힌 환경(읽기는 되는데 쓰기만 실패)에서는 표시가 window.name에만 남아 있을 수 있다.
function readMark(): Mark | null {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(KEY) || 'null');
    if (saved) {
      return saved;
    }
  } catch (e) {
    // sessionStorage 접근 자체가 막힌 환경 — 아래에서 window.name을 본다
  }
  return readWindowNameMark();
}

function writeMark(target: string): void {
  const mark: Mark = { target, at: Date.now() };
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(mark));
  } catch (e) {
    try {
      window.name = WINDOW_NAME_PREFIX + JSON.stringify(mark);
    } catch (e2) {
      // 저장할 방법이 없으면 반복 방지는 포기한다 — 화면 자체는 정상 동작한다.
    }
  }
}

// 공개 화면(첫 화면·시리즈·책·검색·소개)은 서버(Django)가 그린다. React 라우터가 회원 화면 밖의 주소에 오면
// 전체 페이지 이동으로 넘긴다 — 로그인 후 history.push('/') 같은 기존 호출을 하나하나 고치지 않아도 된다.
// nginx 전환 전처럼 같은 주소가 10초 안에 다시 React로 돌아오면 반복하지 않고 안내만 보여 준다.
// 읽기·쓰기를 따로 두는 이유: 저장이 실패해도 이미 읽어 둔 recent 값을 덮어쓰지 않기 위해서다.
//
// 반복 안내(stuck)는 "SPA가 회원 화면 밖의 주소로 처음 열렸을 때"(history.action === 'POP', 첫 로드나
// 실제 뒤로가기)만 걱정할 문제다. 책바구니에서 책을 클릭하는 것처럼 앱 안에서 옮겨온 경우
// (history.action === 'PUSH'/'REPLACE')는 서버 새로고침이 이번이 처음이므로 안내 없이 그대로 넘긴다.
class LeaveSpa extends Component<RouteComponentProps, State> {
  constructor(props: RouteComponentProps) {
    super(props);
    this.state = { stuck: false };
  }

  componentDidMount() {
    const { history } = this.props;
    const target = window.location.pathname + window.location.search;
    if (history.action !== 'POP') {
      writeMark(target);
      window.location.assign(target);
      return;
    }
    const saved = readMark();
    const isRecent = saved && saved.target === target && Date.now() - saved.at < RETRY_WINDOW_MS;
    const recent = Boolean(isRecent);
    writeMark(target);
    if (recent) {
      this.setState({ stuck: true });
    } else {
      window.location.assign(target);
    }
  }

  render() {
    const { stuck } = this.state;
    return stuck ? <p className="LeaveSpa">잠시 점검 중이에요. 조금 뒤 다시 들어와 주세요.</p> : null;
  }
}

export default LeaveSpa;
