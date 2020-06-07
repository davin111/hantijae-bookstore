import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions, stateActions } from '../../../store/actions';
import './BookInBasket.css';


export interface BookProps {
  id: number;
  title: string;
  subtitle: string;
  shortDescription: string;
  fullPrice: number;
  price: number;
  count: number;
  authors: any[];
  history: any;
  me: any;
  basket: any;
  basketStatus: string;
  getMeStatus: string;
  onPutBookInBasket202006NewBook: (bookId: number, count: number, basketId: number) => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
}

class BookInBasket extends Component<BookProps> {
  increase = () => {
    this.props.onPutBookInBasket202006NewBook(
      this.props.id, this.props.count + 1, this.props.basket.id,
    );
  };

  decrease = () => {
    this.props.onPutBookInBasket202006NewBook(
      this.props.id, this.props.count - 1, this.props.basket.id,
    );
  };

  makeZero = () => {
    this.props.onPutBookInBasket202006NewBook(this.props.id, 0, this.props.basket.id);
  };

  render() {
    const authorNames = [];
    for (let i = 0; i < this.props.authors.length; i += 1) {
      authorNames.push(this.props.authors[i].name);
    }
    const authorStr = authorNames.join(' · ');

    const plusDisabled = this.props.basket.bookCount >= this.props.basket.maxBookCount;
    const minusDisabled = this.props.count <= 0;

    return (
      <div className="BookInBasket">
        {/* eslint-disable-next-line */}
        <div className="BookCover" onClick={() => this.props.history.push(`/book=${this.props.id}`)}>
          {/* eslint-disable-next-line */}
          <img src={require('../book_covers/' + this.props.title.replace(':', '').replace('!', '') + '.png')} />
        </div>
        <div className="BookInfoInBasket">
          {/* eslint-disable-next-line */}
          <h1 onClick={() => this.props.history.push(`/book=${this.props.id}`)}>{this.props.title}</h1>
          {/* eslint-disable-next-line */}
          <h3 onClick={() => this.props.history.push(`/book=${this.props.id}`)}>{this.props.subtitle}</h3>
          <h4>{authorStr}</h4>
          <h4 className="FullPrice">
            {this.props.fullPrice}
            원
          </h4>
        </div>
        <button
          className="MakeZeroButton"
          type="button"
          onClick={() => this.makeZero()}
        >
          X
        </button>
        <div className="BookCountInBasket">
          <div className="handle-counter" id="handleCounter">
            <button
              type="button"
              className="counter-plus btn btn-primary"
              onClick={() => this.increase()}
              disabled={plusDisabled}
            >
              +
            </button>
            <input type="text" value={this.props.count} disabled />
            <button
              type="button"
              className="counter-minus btn btn-primary"
              onClick={() => this.decrease()}
              disabled={minusDisabled}
            >
              -
            </button>
          </div>
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  me: state.user.me,
  getMeStatus: state.user.getMeStatus,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onPutBookInBasket: (bookId: number, count: number, basketId: number) => dispatch(
    userActions.putBookInBasket(bookId, count, basketId),
  ),
  onPutBookInBasket202006NewBook: (bookId: number, count: number, basketId: number) => dispatch(
    userActions.putBookInBasket202006NewBook(bookId, count, basketId),
  ),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookInBasket);
