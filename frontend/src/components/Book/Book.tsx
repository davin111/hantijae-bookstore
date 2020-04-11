import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions, stateActions } from '../../store/actions';
import './Book.css';
import BookCountWithCart from '../BookCountWithCart/BookCountWithCart';


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
  suggestLogin: boolean;
}

// eslint-disable-next-line react/prefer-stateless-function
class Book extends Component<BookProps> {
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
        <div className="BookListCart">
          <BookCountWithCart bookId={this.props.id} history={this.props.history} />
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

export default connect(mapStateToProps, mapDispatchToProps)(Book);
