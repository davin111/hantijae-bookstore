import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { stateActions } from '../../store/actions';
import './Book.css';
import BookCountWithCart from '../BookCountWithCart/BookCountWithCart';


export interface BookProps {
  id: number;
  title: string;
  subtitle: string;
  shortDescription: string;
  fullPrice: number;
  price: number;
  visible: boolean;
  authors: any[];
  history: any;
  me: any;
  basket: any;
  basketStatus: string;
  getMeStatus: string;
  published_date: string;
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

    let bookCart = null;
    if (this.props.visible) {
      bookCart = null;
      if (this.props.published_date.split('-')[0] === '2020') {
        if (this.props.id === 108) {
          bookCart = (
            // eslint-disable-next-line
            <h3 className="NotAcceptable"
              onClick={() => window.open('https://www.aladin.co.kr/shop/wproduct.aspx?ItemId=225033583')}
            >
              한티재 신간
            </h3>
          );
        } else if (this.props.id === 109) {
          bookCart = (
            // eslint-disable-next-line
            <h3
              className="NotAcceptable"
              onClick={() => window.open('https://www.aladin.co.kr/shop/wproduct.aspx?ItemId=237230373')}
            >
              한티재 신간
            </h3>
          );
        } else {
          // bookCart = (
          //   <div className="BookListCart">
          //     <BookCountWithCart bookId={this.props.id} history={this.props.history} />
          //   </div>
          // );
          bookCart = (
            // eslint-disable-next-line
            <h3
              className="NotAcceptable"
              onClick={() => window.open('https://www.aladin.co.kr/shop/wproduct.aspx?ItemId=242512574')}
            >
              한티재 신간
            </h3>
          );
        }
      }
    } else {
      bookCart = <h3 className="NotVisible">절판</h3>;
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
        {bookCart}
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
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(Book);
