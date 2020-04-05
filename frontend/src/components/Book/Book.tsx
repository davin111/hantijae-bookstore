import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { FaCartArrowDown } from 'react-icons/lib/fa';

import { userActions, stateActions } from '../../store/actions';
import './Book.css';
import { basketStatus, userStatus } from '../../constants/constants';


export interface BookProps {
  id: number;
  title: string;
  subtitle: string;
  shortDescription: string;
  fullPrice: number;
  price: number;
  authors: any[];
  history: any;
  me: any;
  basket: any;
  basketStatus: string;
  getMeStatus: string;
  onPostBookInBasket: (id: number, count: number) => any;
  onOpenLoginModal: () => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
}

interface State{
  count: number;
}

class Book extends Component<BookProps, State> {
  constructor(props: BookProps) {
    super(props);
    this.state = {
      count: 1,
    };
  }

  clickCartHandler = () => {
    if (this.state.count === 0) {
      return;
    }
    if (this.props.getMeStatus === userStatus.FAILURE || this.props.me.anonymous === true) {
      this.props.onOpenLoginModal();
    } else {
      this.props.onPostBookInBasket(this.props.id, this.state.count)
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

  increase = () => {
    const { count } = this.state;
    this.setState({ count: count + 1 });
  };

  decrease = () => {
    const { count } = this.state;
    this.setState({ count: count - 1 });
  };

  render() {
    const authorNames = [];
    for (let i = 0; i < this.props.authors.length; i += 1) {
      authorNames.push(this.props.authors[i].name);
    }
    const authorStr = authorNames.join(' · ');

    let shortDesc = '';
    if (this.props.shortDescription.length > 100) {
      shortDesc = `${this.props.shortDescription.substr(0, 100)} ...`;
    }

    const plusDisabled = this.state.count >= 10;
    const minusDisabled = this.state.count <= 0;

    return (
      <div className="Book">
        {/* eslint-disable-next-line */}
        <div className="BookCover" onClick={() => this.props.history.push(`/book=${this.props.id}`)}>
          {/* eslint-disable-next-line */}
          <img src={require('./book_covers/' + this.props.title.replace(':', '').replace('!', '') + '.png')} />
        </div>
        <div className="BookInfo">
          {/* eslint-disable-next-line */}
          <h1 onClick={() => this.props.history.push(`/book=${this.props.id}`)}>{this.props.title}</h1>
          {/* eslint-disable-next-line */}
          <h3 onClick={() => this.props.history.push(`/book=${this.props.id}`)}>{this.props.subtitle}</h3>
          <h4>{authorStr}</h4>
          {/* <Rate rate={this.props.rate} voters={this.props.voters} textColor="#607D8B" /> */}
          <div className="BookDescription">
            <p>
              {shortDesc}
            </p>
          </div>
        </div>
        <div className="BookCountWithCart">
          <div className="BookCount">
            <div className="handle-counter" id="handleCounter">
              <button type="button" className="counter-plus btn btn-primary" disabled={plusDisabled} onClick={() => this.increase()}>+</button>
              <input type="text" value={this.state.count} disabled />
              <button type="button" className="counter-minus btn btn-primary" disabled={minusDisabled} onClick={() => this.decrease()}>-</button>
            </div>
          </div>
          <FaCartArrowDown
            className="CartIcon"
            onClick={() => this.clickCartHandler()}
          />
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
  onPostBookInBasket: (id: number, count: number) => dispatch(
    userActions.postBookInBasket(id, count),
  ),
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(Book);
