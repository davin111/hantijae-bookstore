import React, { Component } from 'react';

import bookInfo from '../../../books.json';
import './NavBar.css';

interface Props{
  activeTab: any;
  onFilterClick: (category: any) => void;
}

class NavBar extends Component<Props> {
  onFilterSelect = (category: any) => {
    this.props.onFilterClick(category);
  };

  render() {
    const categories = bookInfo.store.map((x, index) => {
      const categoryName = x.category.charAt(0).toUpperCase() + x.category.slice(1);
      const style = `CategoryButton ${this.props.activeTab === x.category ? 'CategoryButtonActive' : ''}`;
      return (
        <button
          type="button"
          key={categoryName + index.toString()}
          onClick={() => this.onFilterSelect(x.category)}
          className={style}
        >
          {categoryName}
        </button>
      );
    });
    return (
      <div className="NavBar">
        {categories}
      </div>
    );
  }
}

export default NavBar;
