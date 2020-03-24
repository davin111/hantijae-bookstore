import React, { Component } from 'react';
import './Books.css';
import Book, { BookProps } from '../Book/Book';


interface Props{
  books: BookProps[];
}

class Books extends Component<Props> {
  bookCardMaker = (book: BookProps) => (
    <Book
      key={book.name}
      name={book.name}
      image={book.image}
      author={book.author}
      rate={book.rate}
      voters={book.voters}
      people={book.people}
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
