import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './SearchResult.css';
import { Books } from '../../components';

interface Props{
  searchBooksStatus: string;
  books: any;
  onSearchBooks: (search: string) => any;
  history: any;
  location: any;
}

class SearchResult extends Component<Props> {
  componentDidMount() {
    const search = this.props.location.pathname.split('=')[1];
    this.props.onSearchBooks(search);
  }

  componentDidUpdate(prevProps: Props) {
    if (this.props.location !== prevProps.location) {
      const search = this.props.location.pathname.split('=')[1];
      this.props.onSearchBooks(search);
    }
  }

  render() {
    let books = null;
    if (this.props.books.length > 0) {
      books = <Books books={this.props.books} history={this.props.history} />;
    }
    return (
      <div className="BookShelf">
        {books}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  searchBooksStatus: state.book.searchBooksStatus,
  books: state.book.books,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onSearchBooks: (search: string) => dispatch(bookActions.searchBooks(search)),
});

export default connect(mapStateToProps, mapDispatchToProps)(SearchResult);
