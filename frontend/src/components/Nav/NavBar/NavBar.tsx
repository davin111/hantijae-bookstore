import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import './NavBar.css';

interface Props{
  activeTab: string;
  categories: any;
  onFilterClick: (category: any) => void;
}

// interface State{
//   categories: any;
//   activeTab: string;
// }

class NavBar extends Component<Props> {
  // constructor(props: Props) {
  //   super(props);
  //   this.state = {
  //     categories: [],
  //     activeTab: '',
  //   };
  // }

  /* eslint-disable react/no-did-update-set-state */
  // It's OK to use setState if it is wrapped in a condition
  // componentDidUpdate(prevProps: Props) {
  //   if (this.props.categories !== prevProps.categories
  //         || this.props.activeTab !== prevProps.activeTab) {
  //     this.setState({
  //       categories: this.props.categories,
  //       activeTab: this.props.activeTab,
  //     });
  //     console.log('CHANGED');
  //     console.log(prevProps.categories);
  //     console.log(this.props.categories);
  //     console.log(prevProps.activeTab);
  //     console.log(this.props.activeTab);
  //   }
  // }
  /* eslint-enable react/no-did-update-set-state */

  onFilterSelect = (category: any) => {
    this.props.onFilterClick(category);
  };

  render() {
    let categories = null;
    if (this.props.categories.length > 0) {
      categories = this.props.categories.map((category: any) => {
        const categoryName = category.name.charAt(0).toUpperCase() + category.name.slice(1);
        const style = `CategoryButton ${this.props.activeTab === category.name ? 'CategoryButtonActive' : ''}`;
        return (
          <button
            type="button"
            key={categoryName}
            onClick={() => this.onFilterSelect(category.name)}
            className={style}
          >
            {categoryName}
          </button>
        );
      });
    }
    return (
      <div className="NavBar">
        {categories}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
});

export default connect(mapStateToProps, mapDispatchToProps)(NavBar);
