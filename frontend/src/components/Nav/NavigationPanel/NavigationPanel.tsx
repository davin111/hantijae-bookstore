import React, { Component } from 'react';

import NavBar from '../NavBar/NavBar';
import './NavigationPanel.css';

interface Props{
  history: any;
}

class NavigationPanel extends Component<Props> {
  render() {
    return (
      <div className="NavigationPanel">
        <div className="PopularBy">
          <span>Popular by Genre</span>
        </div>
        <NavBar
          history={this.props.history}
        />
      </div>
    );
  }
}

export default NavigationPanel;
