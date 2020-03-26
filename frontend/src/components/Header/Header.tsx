import React, { Component } from 'react';

import Title from './Title/Title';
import SearchBar from './SearchBar/SearchBar';

import './Header.css';


// eslint-disable-next-line react/prefer-stateless-function
class Header extends Component {
  render() {
    return (
      <header>
        <SearchBar />
        <Title />
      </header>
    );
  }
}

export default Header;
