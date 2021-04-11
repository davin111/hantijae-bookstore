import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
// import ReactPlayer from 'react-player';

import { bookActions, stateActions, userActions } from '../../store/actions';
import { basketStatus, userStatus } from '../../constants/constants';
import { LoginModal, FullBasketModal, BasketInfoModal } from '../../components';
import './HantijaePage.css';

interface Props {
  location: any;
  history: any;
  me: any;
  getBookStatus: string;
  getMeStatus: string;
  basketStatus: string;
  onGetBook: (id: number) => any;
  onPostBookInBasket202006NewBook: (id: number, count: number) => any;
  onOpenLoginModal: () => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
}

class HantijaePage extends Component<Props> {
  componentDidMount() {
    window.scrollTo(0, 0);
  }

  clickPostBookHandler = () => {
    if (this.props.getMeStatus === userStatus.FAILURE || this.props.me.anonymous === true) {
      this.props.onOpenLoginModal();
    } else {
      this.props.onPostBookInBasket202006NewBook(110, 1)
        .then(() => {
          if (this.props.basketStatus === basketStatus.SUCCESS) {
            this.props.onOpenBasketInfoModal();
          }
          if (this.props.basketStatus === basketStatus.FAILURE_MAX_BOOK) {
            this.props.onOpenFullBasketModal();
          }
        });
    }
  };

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
            지난 10년 동안 인문·사회·문학·청소년 분야의 단행본 120종을 펴냈습니다.
            사람과 사람, 사람과 자연, 오늘 세대와 내일 세대가 공존하는 사회에 보탬이 되는 책을 만들기 위해 노력하고 있습니다.
          </p>
        </div>
        {/* <hr className="HantijaeCenterLine" />
        <h3 className="NewBookTitle">
          『성서, 퀴어를 옹호하다』 텀블벅 펀딩 진행중!
        </h3>
        <h3 className="EventTitle">
          왜 개신교는 그렇게 성소수자를 부정할까?
          <br />
          정말로 성서는 동성애를 금지하고 있을까?
        </h3>
        <p className="EventDescription">
          일정 금액 이상 후원 시 금속 뱃지와 스티커를 증정합니다.
        </p>
        <hr className="HantijaeCenterLineSmall" />
        <h3 className="NewBookTitlesInPage">
          『성서, 퀴어를 옹호하다』
          <br />
          ― 성서학자가 들려주는 기독교와 성소수자 이야기
        </h3>
        <div className="NewBookStand"> */}
        {/* eslint-disable-next-line */}
          {/* <img src={require('../BookDetail/book_covers_3d/성서, 퀴어를 옹호하다.jpeg')} />
        </div>
        <Button
          type="button"
          onClick={() => window.open('https://tumblbug.com/queerinbible')}
          variant="contained"
          color="primary"
          size="medium"
          style={{
            backgroundColor: '#7EC7C5',
          }}
        >
          프로젝트 밀어주기
        </Button> */}
        {/* <Button
          type="button"
          onClick={() => this.clickPostBookHandler()}
          variant="contained"
          color="secondary"
          size="medium"
        >
          책바구니에 담기
        </Button> */}
        {/* <p className="EventDescription">
          ♥ 펀딩 기간 : 2020년 7월 17일(금) ~ 8월 20일(목)
          <br />
          ♥ 예상 선물 수령일 : 9월 15일(화)
          <br />
          &nbsp;&nbsp;8월 20일 - 펀딩 마감
          <br />
          &nbsp;&nbsp;9월 7일 - 모금액 정산 완료, 제작비 결제
          <br />
          &nbsp;&nbsp;9월 15일 - 예상 선물 수령일
          <br />
          ♥ 문의 : 053-743-8368 | hantibooks@gmail.com
        </p>
        <LoginModal history={this.props.history} />
        <FullBasketModal history={this.props.history} />
        <BasketInfoModal history={this.props.history} /> */}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  getMeStatus: state.user.getMeStatus,
  basketStatus: state.user.basketStatus,
  book: state.book.getBook,
  me: state.user.me,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBook: (id: number) => dispatch(bookActions.getBook(id)),
  onPostBookInBasket202006NewBook: (id: number, count: number) => dispatch(
    userActions.postBookInBasket202006NewBook(id, count),
  ),
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(HantijaePage);
