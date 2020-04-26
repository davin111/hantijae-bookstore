import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import ReactPlayer from 'react-player';

import { bookActions } from '../../store/actions';
import './HantijaePage.css';

interface Props {
  location: any;
  getBookStatus: string;
  onGetBook: (id: number) => any;
  history: any;
}

class HantijaePage extends Component<Props> {
  componentDidMount() {
    window.scrollTo(0, 0);
  }

  render() {
    return (
      <div className="HantijaePage">
        <div className="HantijaeUpper">
          <h1 className="HantijaeTitle">도서출판 한티재는...</h1>
          <div className="HantijaeImage">
            {/* eslint-disable-next-line */}
            <img src={require(`./kiki.jpeg`)} />
          </div>
        </div>
        <div className="HantijaeDescription">
          <p>
            도서출판 한티재는 권정생 선생님의 소설 『한티재 하늘』에서 이름을 따온, 대구의 작은 출판사입니다.
            지난 10년 동안 인문·사회·문학·청소년 분야의 단행본 109종을 펴냈습니다.
            사람과 사람, 사람과 자연, 오늘 세대와 내일 세대가 공존하는 사회에 보탬이 되는 책을 만들기 위해 노력하고 있습니다.
          </p>
        </div>
        <hr className="HantijaeCenterLine" />
        <h3 className="NewBookTitle">
          한티재 신간
        </h3>
        <h3 className="EventTitle">
          전태일 50주기 공동 출판 프로젝트 ─ 너는 나다
        </h3>
        <div className="NewBookStand">
          {/* eslint-disable-next-line */}
          <img src={require('./new_book.png')} />
        </div>
        <ReactPlayer
          className="HantijaeYouTube"
          url="https://www.youtube.com/watch?v=bW3SAa9jL9Q"
          playing
          controls
        />
        <Button
          type="button"
          onClick={() => this.props.history.push('/book=109')}
          variant="contained"
          color="primary"
          size="medium"
        >
          바로가기
        </Button>
        <p className="EventDescription">
          <h3>
            “우리 생애의 노동은 인간다운가”
          </h3>
          <p>
            일, 밥, 집, 시간, 공부 …
            누구도 자유로울 수 없는 삶의 문제들을 키워드로,
            전태일의 생애와 오늘 여기 청년들의 현실을 씨실과 날실로 엮었다.
            사람과 세상을 대하는 전혀 다른 시야를 열어 준 전태일과 함께
            한국 사회 ‘그늘의 지도’ 곳곳을 찾아나서는 길 위의 인문학.
            우리 일상을 지배하는 생각과 말들의 규칙에 맞서
            행복과 사랑의 공공성을 되찾으려는, 아프지만 유쾌한 여정.
          </p>
        </p>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  book: state.book.getBook,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBook: (id: number) => dispatch(bookActions.getBook(id)),
});

export default connect(mapStateToProps, mapDispatchToProps)(HantijaePage);
