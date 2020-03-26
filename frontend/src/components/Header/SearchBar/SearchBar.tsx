import React, { Component } from 'react';
import './SearchBar.css';
import { FaSearch } from 'react-icons/lib/fa';

// eslint-disable-next-line react/prefer-stateless-function
class SearchBar extends Component {
  render() {
    return (
      <div className="SearchBar">
        <FaSearch className="iconSearch" />
        <input placeholder="Search" />
      </div>
    );
  }
}

export default SearchBar;
