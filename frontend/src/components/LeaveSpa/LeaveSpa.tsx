import React, { Component } from 'react';

const KEY = 'hantijae:leave-spa';
const RETRY_WINDOW_MS = 10000;

interface State {
  stuck: boolean;
}

// 공개 화면(첫 화면·시리즈·책·검색·소개)은 서버(Django)가 그린다. React 라우터가 회원 화면 밖의 주소에 오면
// 전체 페이지 이동으로 넘긴다 — 로그인 후 history.push('/') 같은 기존 호출을 하나하나 고치지 않아도 된다.
// nginx 전환 전처럼 같은 주소가 10초 안에 다시 React로 돌아오면 반복하지 않고 안내만 보여 준다.
class LeaveSpa extends Component<{}, State> {
  constructor(props: {}) {
    super(props);
    this.state = { stuck: false };
  }

  componentDidMount() {
    const target = window.location.pathname + window.location.search;
    let recent = false;
    try {
      const saved = JSON.parse(window.sessionStorage.getItem(KEY) || 'null');
      recent = Boolean(saved && saved.target === target && Date.now() - saved.at < RETRY_WINDOW_MS);
      window.sessionStorage.setItem(KEY, JSON.stringify({ target, at: Date.now() }));
    } catch (e) {
      recent = false;
    }
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
