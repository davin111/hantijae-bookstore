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
      published_date={book.published_date}
      history={this.props.history}
      visible={book.visible}
      aladin_url={book.aladin_url}
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
