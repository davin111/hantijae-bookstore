import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { FaSearch } from 'react-icons/lib/fa';

import { bookActions } from '../../../store/actions';
import './SearchBar.css';

interface Props {
  searchBooksStatus: string;
  books: any;
  onSearchBooks: (search: string) => any;
  history: any;
}

interface State {
  search: string;
}

class SearchBar extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      search: '',
    };
  }

  keyPressHandler = (e: any) => {
    if (this.state.search && e.charCode === 13) {
      this.props.history.push(`/search=${this.state.search}`);
    }
  };

  render() {
    return (
      <div className="SearchBar">
        <FaSearch className="iconSearch" />
        <input
          placeholder="검색"
          value={this.state.search}
          onChange={(e) => this.setState({ search: e.target.value })}
          onKeyPress={(e) => this.keyPressHandler(e)}
        />
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

export default connect(mapStateToProps, mapDispatchToProps)(SearchBar);
