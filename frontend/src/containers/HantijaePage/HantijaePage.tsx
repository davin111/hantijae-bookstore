import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
// import ReactPlayer from 'react-player';

import { bookActions, stateActions, userActions } from '../../store/actions';
import { basketStatus, userStatus, bookStatus } from '../../constants/constants';
import { LoginModal, FullBasketModal, BasketInfoModal } from '../../components';
import './HantijaePage.css';

interface Props {
  location: any;
  history: any;
  me: any;
  bookCount: number;
  getBookStatus: string;
  getBookCountStatus: string;
  getMeStatus: string;
  basketStatus: string;
  onGetBook: (id: number) => any;
  onGetBookCount: () => any;
  onPostBookInBasket202006NewBook: (id: number, count: number) => any;
  onOpenLoginModal: () => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
}

class HantijaePage extends Component<Props> {
  componentDidMount() {
    window.scrollTo(0, 0);
    const { onGetBookCount } = this.props;
    onGetBookCount();
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
    let bookCount = 0;
    if (this.props.getBookCountStatus === bookStatus.SUCCESS) {
      bookCount = this.props.bookCount;
    }

    return (
      <div className="HantijaePage">
        <div className="HantijaeUpper">
          <h1 className="HantijaeTitle">도서출판 한티재는...</h1>
          <div className="HantijaeImage">
            <img src={"https://hantijae-assets.s3.ap-northeast-2.amazonaws.com/misc/kiki.jpeg"} />
          </div>
        </div>
        <div className="HantijaeDescription">
          <p>
            도서출판 한티재는 권정생 선생님의 소설 『한티재 하늘』에서 이름을 따온, 대구의 작은 출판사입니다.
            지난 10년 동안 인문·사회·문학·청소년 분야의 단행본
            {' '}
            {bookCount}
            종을 펴냈습니다.
            사람과 사람, 사람과 자연, 오늘 세대와 내일 세대가 공존하는 사회에 보탬이 되는 책을 만들기 위해 노력하고 있습니다.
          </p>
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  getBookCountStatus: state.book.getBookCountStatus,
  getMeStatus: state.user.getMeStatus,
  basketStatus: state.user.basketStatus,
  bookCount: state.book.bookCount,
  book: state.book.getBook,
  me: state.user.me,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBook: (id: number) => dispatch(bookActions.getBook(id)),
  onGetBookCount: () => dispatch(bookActions.getBookCount()),
  onPostBookInBasket202006NewBook: (id: number, count: number) => dispatch(
    userActions.postBookInBasket202006NewBook(id, count),
  ),
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(HantijaePage);
