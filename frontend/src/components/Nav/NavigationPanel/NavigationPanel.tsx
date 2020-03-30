import React, { Component } from 'react';

import NavBar from '../NavBar/NavBar';
import SearchBar from '../../Header/SearchBar/SearchBar';
import './NavigationPanel.css';

interface Props{
  history: any;
}

class NavigationPanel extends Component<Props> {
  render() {
    return (
      <div className="NavigationPanel">
        <SearchBar />
        <NavBar
          history={this.props.history}
        />
      </div>
    );
  }
}

export default NavigationPanel;
