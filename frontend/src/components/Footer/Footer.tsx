import React, { Component } from 'react';

import './Footer.css';

const CHANNELS: [string, string][] = [
  ['블로그', 'https://blog.naver.com/hantijae_publisher'],
  ['인스타그램', 'https://www.instagram.com/hantijae'],
  ['X', 'https://x.com/hantijae_book'],
  ['페이스북', 'https://www.facebook.com/hantijae'],
  ['유튜브', 'https://www.youtube.com/channel/UCL_2QimPtgoDX3Y8e0qOBOA'],
];

// 공개 화면(web/templates/web/base.html) 푸터와 같은 내용을 유지한다.
// eslint-disable-next-line react/prefer-stateless-function
class Footer extends Component {
  render() {
    return (
      <footer className="SpaFooter">
        <p className="SpaFooterName">도서출판 한티재</p>
        <address>
          42087 대구시 수성구 달구벌대로 492길 15 (2층)
          <br />
          TEL 053-743-8368 · FAX 053-743-8367
          <br />
          <a href="mailto:hantibooks@gmail.com">hantibooks@gmail.com</a>
        </address>
        <nav className="SpaFooterChannels" aria-label="한티재 채널">
          {CHANNELS.map(([label, url]) => (
            <a key={url} href={url} target="_blank" rel="noopener noreferrer">{label}</a>
          ))}
        </nav>
      </footer>
    );
  }
}

export default Footer;
