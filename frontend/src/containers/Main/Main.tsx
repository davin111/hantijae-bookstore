import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { BookShelf } from '../../components';
import { bookActions } from '../../store/actions';
import './Main.css';

interface Props {
  onGetBooks: () => void;
}

class Main extends Component<Props> {
  componentDidMount() {
    const { onGetBooks } = this.props;
    // onGetBooks();
  }


  render() {
    return (
      <BookShelf />
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
