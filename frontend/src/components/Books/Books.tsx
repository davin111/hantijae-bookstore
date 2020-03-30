import React, { Component } from 'react';
import './Books.css';
import Book, { BookProps } from '../Book/Book';


interface Props{
  books: BookProps[];
  history: any;
}

class Books extends Component<Props> {
  bookCardMaker = (book: any) => (
    <Book
      key={book.id}
      id={book.id}
      title={book.title}
      subtitle={book.subtitle}
      shortDescription={book.short_description}
      fullPrice={book.full_price}
      price={book.price}
      authors={book.authors}
      history={this.props.history}
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
      <div className="Books">
        {bookCards}
      </div>
    );
  }
}

export default Books;
