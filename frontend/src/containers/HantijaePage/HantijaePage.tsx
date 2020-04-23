import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

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
        {/* <hr className="HantijaeCenterLine" />
        <h3 className="EventTitle">
          한티재 10주년 기념 ‘10권 10만 원 책바구니’ 특판 이벤트를 진행하고 있습니다!
        </h3>
        <p className="EventDescription">
          <li>
            책의 정가와 상관 없이 한티재 책 최대 10권을 10만 원에 구입하실 수 있습니다.
            단, 10권보다 적게 담거나, 정가 총액이 10만 원보다 적어도 결제 금액은 10만 원입니다^^
          </li>
          <li>
            특판 이벤트에서 2020년 올해 나온 신간은 제외됩니다.
          </li>
          <li>
            한티재 온라인 책창고를 둘러보시고 책바구니에 책을 담아주세요. 지난 10년 동안 한티재는 총 108종의 단행본을 출간했습니다(절판 12종 포함).
          </li>
          <li>
            문의: hantibooks@gmail.com / 053-743-8368
          </li>
        </p> */}
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
