import React, { Component } from 'react';
import { FaHeartO, FaHeart } from 'react-icons/lib/fa';
import './Book.css';

export interface BookProps {
  name: string;
  image: string;
  author: string;
  rate: any;
  voters: any;
  people: any;
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

  render() {
    let like = null;
    if (this.state.liked) {
      like = <FaHeart className="icon" onClick={() => { this.isLiked(); }} />;
    } else {
      like = <FaHeartO className="icon" onClick={() => { this.isLiked(); }} />;
    }

    return (
      <div className="Book">
        <div className="BookCover">
          {/* eslint-disable-next-line */}
          <img src={require(`./booksImgs/${this.props.image}`)} />
        </div>
        <div className="BookInfo">
          <h1>{this.props.name}</h1>
          <p className="Author">
            by
            {' '}
            {this.props.author}
          </p>
          {/* <Rate rate={this.props.rate} voters={this.props.voters} textColor="#607D8B" /> */}
          <div className="BookDescription">
            <p>
              Lorem ipsum dolor sit amet, consectetur adipiscing elit,
              sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.
            </p>
          </div>
        </div>
        {like}
      </div>
    );
  }
}

export default Book;
