import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../store/actions';
import { BooksInBasket } from '../../components';
import './BookBasket.css';
import { basketStatus } from '../../constants/constants';

interface Props {
  location: any;
  basket: any;
  basketStatus: string;
  onGetBasket: () => any;
  history: any;
}


class BookBasket extends Component<Props> {
  componentDidMount() {
    this.props.onGetBasket();
  }

  render() {
    let books = null;
    console.log(this.props.basket);
    if (this.props.basketStatus === basketStatus.SUCCESS) {
      books = <BooksInBasket books={this.props.basket.books} history={this.props.history} />;
    }

    let totalPrice = 0;
    for (let i = 0; i < this.props.basket.books.length; i += 1) {
      totalPrice += (this.props.basket.books[i].full_price * this.props.basket.books[i].count);
    }

    return (
      <div className="BookBasketPage">
        <h1 className="BookBasketTitle">책바구니 내역</h1>
        <h2 className="BookBasketTotalCount">
          {this.props.basket.bookCount}
          /
          {this.props.basket.maxBookCount}
          권
        </h2>
        {books}
        <div className="BookBasketSummary">
          {totalPrice}
          원
          {' '}
          ->
          {' '}
          {this.props.basket.maxPrice}
          원
        </div>
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
});

export default connect(mapStateToProps, mapDispatchToProps)(BookBasket);
