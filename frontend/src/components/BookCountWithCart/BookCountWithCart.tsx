import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { FaCartArrowDown } from 'react-icons/lib/fa';

import { userActions, stateActions } from '../../store/actions';
import './BookCountWithCart.css';
import { basketStatus, userStatus } from '../../constants/constants';


export interface BookProps {
  bookId: number;
  history: any;
  me: any;
  basket: any;
  basketStatus: string;
  getMeStatus: string;
  onPostBookInBasket: (id: number, count: number) => any;
  onOpenLoginModal: () => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
  suggestLogin: boolean;
}

interface State{
  count: number;
}

class BookCountWithCart extends Component<BookProps, State> {
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
    if ((this.props.getMeStatus === userStatus.FAILURE || this.props.me.anonymous === true)
      && this.props.suggestLogin) {
      this.props.onOpenLoginModal();
    } else {
      this.props.onPostBookInBasket(this.props.bookId, this.state.count)
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
    const plusDisabled = this.state.count >= 10;
    const minusDisabled = this.state.count <= 0;

    return (
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
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  me: state.user.me,
  getMeStatus: state.user.getMeStatus,
  basket: state.user.basket,
  suggestLogin: state.state.suggestLogin,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onPostBookInBasket: (id: number, count: number) => dispatch(
    userActions.postBookInBasket(id, count),
  ),
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookCountWithCart);
