import React, { Component } from 'react';

import Title from './Title/Title';
import User from './User/User';
import SearchBar from './SearchBar/SearchBar';
import NavigationPanel from '../Nav/NavigationPanel/NavigationPanel';

import './Header.css';

interface Props {
  history: any;
}

// eslint-disable-next-line react/prefer-stateless-function
class Header extends Component<Props> {
  render() {
    return (
      <div>
        <header>
          <SearchBar />
          <Title history={this.props.history} />
        </header>
        <NavigationPanel
          history={this.props.history}
        />
      </div>
    );
  }
}

export default Header;
