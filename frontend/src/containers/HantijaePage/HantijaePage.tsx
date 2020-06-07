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
            지난 10년 동안 인문·사회·문학·청소년 분야의 단행본 110종을 펴냈습니다.
            사람과 사람, 사람과 자연, 오늘 세대와 내일 세대가 공존하는 사회에 보탬이 되는 책을 만들기 위해 노력하고 있습니다.
          </p>
        </div>
        <hr className="HantijaeCenterLine" />
        <h3 className="NewBookTitle">
          한티재 신간
        </h3>
        <h3 className="EventTitle">
          “사랑과 위로를 나에게 선물하세요”
          <br />
          ― 『당신이 나의 백신입니다』 저자 자필 사인본 이벤트
        </h3>
        <p className="EventDescription">
          따뜻한 의사 김동은 선생님의 첫 책 출간을 기념하여
          <br />
          저자 자필 사인본 이벤트를 준비했습니다.
          <br />
          한티재 온라인 책창고에서 책을 주문하시면,
          <br />
          힘들고 아픈 사람 곁에 늘 함께 있는 선생님의
          <br />
          따뜻한 글씨를 책에 담아 보내드립니다.
          <br />
          많은 신청 부탁드립니다!
        </p>
        <hr className="HantijaeCenterLineSmall" />
        <h3 className="NewBookTitlesInPage">
          『당신이 나의 백신입니다』
          <br />
          ― 감염병과 혐오의 시대, 의사 김동은이 만난 아름다운 사람들
        </h3>
        <h3 className="NewBookInfosInPage">
          김동은 지음
          <br />
          (2020년 6월 22일 출간 | 15,000원)
        </h3>
        <div className="NewBookStand">
          {/* eslint-disable-next-line */}
          <img src={require('../BookDetail/book_covers_3d/당신이 나의 백신입니다.png')} />
        </div>
        <Button
          type="button"
          onClick={() => this.props.history.push('/book=110')}
          variant="contained"
          color="primary"
          size="medium"
        >
          책 보러가기
        </Button>
        <Button
          type="button"
          onClick={() => this.clickPostBookHandler()}
          variant="contained"
          color="secondary"
          size="medium"
        >
          책바구니에 담기
        </Button>
        <p className="EventDescription">
          ♥ 이벤트 기간 : 2020년 6월 8일(월) ~ 6월 20일(토)
          <br />
          ♥ 책 발송일 : 6월 22일(월)
          <br />
          ♥ 이벤트 참가 방법
          <br />
          &nbsp;&nbsp;1. 한티재 온라인 책창고에서 회원 가입을 합니다.
          <br />
          &nbsp;&nbsp;2. 『당신이 나의 백신입니다』를 주문합니다.
          <br />
          &nbsp;&nbsp;3. 주문 단계에서, 사인 받을 분의 이름을 확인하여 정확히 입력해주세요.
          <br />
          &nbsp;&nbsp;4. ‘주문 완료’ 버튼을 누르고 결제해주세요. 결제가 확인되어야 발송됩니다.
          <br />
          ♥ 문의 : 053-743-8368 | hantibooks@gmail.com
        </p>
        <LoginModal history={this.props.history} />
        <FullBasketModal history={this.props.history} />
        <BasketInfoModal history={this.props.history} />
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
