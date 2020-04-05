import React, { Component } from 'react';
import './BooksInBasket.css';
import BookInBasket, { BookProps } from '../../Book/BookInBasket/BookInBasket';


interface Props{
  books: BookProps[];
  history: any;
}

class BooksInBasket extends Component<Props> {
  bookCardMaker = (book: any) => (
    <BookInBasket
      key={book.id}
      id={book.id}
      title={book.title}
      subtitle={book.subtitle}
      shortDescription={book.short_description}
      fullPrice={book.full_price}
      price={book.price}
      authors={book.authors}
      history={this.props.history}
      count={book.count}
      // rate={book.rate}
      // voters={book.voters}
      // people={book.people}
    />
  );

  render() {
    const bookCards = this.props.books.map(
      (book: BookProps) => this.bookCardMaker(book),
    );

    return (
      <div className="BooksInBasket">
        {bookCards}
      </div>
    );
  }
}

export default BooksInBasket;
