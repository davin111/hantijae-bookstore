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
    let books = null;

    if (this.props.basketStatus === basketStatus.SUCCESS && Object.keys(this.props.basket).length > 0) {
      books = <BooksInBasket books={this.props.basket.books} history={this.props.history} />;
    }

    let bookBasketStatus = '책 담는 중';
    if (this.props.basket.status === 2) {
      bookBasketStatus = '주문 완료';
    } else if (this.props.basket.status === 3) {
      bookBasketStatus = '결제 확인';
    } else if (this.props.basket.status === 4) {
      bookBasketStatus = '배송 완료';
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
        <h2 className="BookBasketStatus">
          {bookBasketStatus}
        </h2>
        <h2 className="BookBasketTotalCount">
          {this.props.basket.bookCount}
          /
          {this.props.basket.maxBookCount}
          권
        </h2>
        {books}
        <div className="BookBasketSummary">
          {this.props.basket.totalPrice}
          원
          {' '}
          -&gt;
          {' '}
          {this.props.basket.maxPrice}
          원
        </div>
        <Button
          id="OrderButton"
          variant="contained"
          color="primary"
          className={classes.button}
          onClick={() => this.props.history.push('/order')}
          endIcon={<ReceiptIcon className="ReceiptIcon" />}
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
