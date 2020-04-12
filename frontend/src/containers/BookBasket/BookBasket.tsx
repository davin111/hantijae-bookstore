import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import ReceiptIcon from '@material-ui/icons/Receipt';
import { createStyles, withStyles } from '@material-ui/core/styles';

import { userActions } from '../../store/actions';
import { BooksInBasket } from '../../components';
import './BookBasket.css';
import BookBasketImg from './bookbasket_won.png';
import { basketStatus } from '../../constants/constants';

interface Props {
  location: any;
  basket: any;
  basketStatus: string;
  onGetBasket: () => any;
  history: any;
  classes: any;
  onGetMe: () => any;
}

const styles = (theme: any) => createStyles({
  button: {
    margin: theme.spacing(1),
  },
});


class BookBasket extends Component<Props> {
  componentDidMount() {
    this.props.onGetMe()
      .then(() => {
        this.props.onGetBasket();
      });
  }

  render() {
    const { classes } = this.props;
    let books = (
      <h3 className="NoResultBasket">
        책바구니 내역이 없습니다. 책을 담으러 가볼까요?
      </h3>
    );
    let summary = null;
    let bookCount = 0;
    let maxBookCount = 10;

    if (this.props.basketStatus === basketStatus.SUCCESS
      && Object.keys(this.props.basket).length > 0) {
      if (Array.isArray(this.props.basket.books) && this.props.basket.books.length > 0) {
        books = <BooksInBasket books={this.props.basket.books} history={this.props.history} />;
        summary = (
          <div className="BookBasketSummary">
            <del className="OriginalPrice">
              {this.props.basket.totalPrice}
              원
            </del>
            {' '}
            →
            {' '}
            {this.props.basket.maxPrice}
            원
          </div>
        );
        bookCount = this.props.basket.bookCount;
        maxBookCount = this.props.basket.maxBookCount;
      }
    }

    return (
      <div className="BookBasketPage">
        <div className="BookBasketTitle">
          {/* eslint-disable-next-line */}
          <img className="BookBasketWonImg" src={BookBasketImg} />
          <h1>
            책바구니 내역
          </h1>
        </div>
        <h2 className="BookBasketTotalCount">
          {bookCount}
          /
          {maxBookCount}
          권
        </h2>
        {books}
        {summary}
        <Button
          id="OrderButton"
          variant="contained"
          color="primary"
          className={classes.button}
          onClick={() => this.props.history.push('/order')}
          endIcon={<ReceiptIcon className="ReceiptIcon" />}
          disabled={!Array.isArray(this.props.basket.books) || this.props.basket.books.length === 0}
        >
          주문하기
        </Button>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBasket: () => dispatch(userActions.getBasket()),
  onGetMe: () => dispatch(userActions.getMe()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(BookBasket));
