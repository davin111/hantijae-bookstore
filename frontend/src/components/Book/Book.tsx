import React, { Component } from 'react';
import { FaHeartO, FaHeart } from 'react-icons/lib/fa';
import './Book.css';

export interface BookProps {
  id: number;
  title: string;
  subtitle: string;
  shortDescription: string;
  fullPrice: number;
  price: number;
  // image: string;
  authors: any[];
  // rate: any;
  // voters: any;
  // people: any;
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

    const authors = this.props.authors.map(
      (author: any) => (
        <p className="Author" key={author.id}>
          {author.name}
        </p>
      ),
    );

    return (
      <div className="Book">
        <div className="BookCover">
          {/* eslint-disable-next-line */}
          <img src={require(`./booksImgs/3.jpg`)} />
        </div>
        <div className="BookInfo">
          <h1>{this.props.title}</h1>
          {authors}
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
