import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { Book } from '../../components';
import { bookActions } from '../../store/actions';

interface Props {
  onGetBooks: () => void;
  books: any;
}

class Main extends Component<Props> {
  componentDidMount() {
    const { onGetBooks } = this.props;
    onGetBooks();
  }

  bookCardMaker = (book: any) => (
    <Book key={book.id} title={book.title} description={book.description} />
  );

  render() {
    const { books } = this.props;
    const bookCards = books.map(
      (book: any) => this.bookCardMaker(book),
    );

    return (
      <div className="main">
        <div className="book-list">
          { bookCards }
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  books: state.book.books,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBooks: () => dispatch(bookActions.getBooks()),
});

export default connect(mapStateToProps, mapDispatchToProps)(Main);
