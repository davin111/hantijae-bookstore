import React, { Component } from 'react';
import './BookShelf.css';
import NavigationPanel from '../Nav/NavigationPanel/NavigationPanel';
import Books from '../Books/Books';
import bookInfo from '../../books.json';


interface State{
  activeFilter: string;
}

class BookShelf extends Component<{}, State> {
  constructor(props: any) {
    super(props);
    this.state = {
      activeFilter: 'business',
    };
  }

  onFilterChange = (filter: string) => {
    this.setState({ activeFilter: filter });
  };

  render() {
    let currentBooks: any[] = [];
    for (let i = 0; i < bookInfo.store.length; i += 1) {
      if (bookInfo.store[i].category === this.state.activeFilter) {
        currentBooks = bookInfo.store[i].books;
        break;
      }
    }
    console.log(currentBooks);
    return (
      <div className="BookShelf">
        <NavigationPanel
          onMainFilterClick={this.onFilterChange}
          activeTab={this.state.activeFilter}
        />
        <Books books={currentBooks} />
      </div>
    );
  }
}

export default BookShelf;
