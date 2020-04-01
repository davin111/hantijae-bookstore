import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { FaHeartO, FaHeart, FaCartArrowDown } from 'react-icons/lib/fa';

import { userActions } from '../../store/actions';
import './Book.css';
import { basketStatus } from '../../constants/constants';


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
  onPostBookInBasket: (id: number) => any;
}

interface State{
  liked: any;
}

class Book extends Component<BookProps, State> {
  constructor(props: BookProps) {
    super(props);
    this.state = {
      liked: false,
    };
  }

  isLiked = () => {
    const prevLiked = this.state.liked;
    this.setState({ liked: !prevLiked });
  };

  clickCartHandler = () => {
    this.props.onPostBookInBasket(this.props.id)
    .then(() => {
      if (this.props.basketStatus === basketStatus.SUCCESS) {

      };
      if (this.props.basketStatus === basketStatus.FAILURE_MAX_BOOK) {
        
      };
    })
  };

  render() {
    let like = null;
    if (this.state.liked) {
      like = <FaHeart className="icon" onClick={() => { this.isLiked(); }} />;
    } else {
      like = <FaHeartO className="icon" onClick={() => { this.isLiked(); }} />;
    }
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
        <FaCartArrowDown
          className="CartIcon"
          onClick={() => this.clickCartHandler()}
        />
        {/* like */}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  me: state.user.me,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onPostBookInBasket: (id: number) => dispatch(userActions.postBookInBasket(id)),
});

export default connect(mapStateToProps, mapDispatchToProps)(Book);
