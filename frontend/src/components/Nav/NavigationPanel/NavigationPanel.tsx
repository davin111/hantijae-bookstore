import React, { Component } from 'react';

import NavBar from '../NavBar/NavBar';
import './NavigationPanel.css';

interface Props{
  activeTab: any;
  onMainFilterClick: (filter: any) => void;
  categories: any;
}

class NavigationPanel extends Component<Props> {
  onCategorySelect = (filter: any) => {
    this.props.onMainFilterClick(filter);
  };

  render() {
    return (
      <div className="NavigationPanel">
        <div className="PopularBy">
          <span>Popular by Genre</span>
        </div>
        <NavBar
          onFilterClick={this.onCategorySelect}
          activeTab={this.props.activeTab}
          categories={this.props.categories}
        />
      </div>
    );
  }
}

export default NavigationPanel;