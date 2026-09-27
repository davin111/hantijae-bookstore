import React, { Component } from 'react';

import './Header.css';

const TITLE_IMAGE = 'https://hantijae-assets.s3.ap-northeast-2.amazonaws.com/misc/hantijae-bookstore-title.png';

// 회원 화면 머리글. 공개 화면으로는 일반 링크(전체 페이지 이동)로 넘어간다.
// eslint-disable-next-line react/prefer-stateless-function
class Header extends Component {
  render() {
    return (
      <header className="SpaHeader">
        <a href="/" className="SpaHeaderBrand">
          <img src={TITLE_IMAGE} alt="한티재 온라인 책창고" />
        </a>
        <a href="/" className="SpaHeaderBack">← 한티재 책 목록</a>
      </header>
    );
  }
}

export default Header;
