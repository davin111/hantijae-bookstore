import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './BookShelf.css';
import NavigationPanel from '../Nav/NavigationPanel/NavigationPanel';
import Books from '../Books/Books';
import { categoryStatus } from '../../constants/constants';

interface Props{
  categories: any;
  getCategoryStatus: string;
  onGetCategories: () => any;
}
interface State{
  activeTab: string;
}

class BookShelf extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      activeTab: '',
    };
  }

  componentDidMount() {
    this.props.onGetCategories()
      .then(() => {
        let activeTab = '';
        if (this.props.getCategoryStatus === categoryStatus.SUCCESS) {
          activeTab = this.props.categories[0].name;
          this.setState({ activeTab });
        }
      })
      .catch(() => {});
  }

  onTabChange = (tab: string) => {
    this.setState({ activeTab: tab });
  };

  render() {
    let currentBooks: any[] = [];
    for (let i = 0; i < this.props.categories.length; i += 1) {
      if (this.props.categories[i].name === this.state.activeTab) {
        currentBooks = this.props.categories[i].books;
        break;
      }
    }

    return (
      <div className="BookShelf">
        <NavigationPanel
          onMainFilterClick={this.onTabChange}
          activeTab={this.state.activeTab}
          categories={this.props.categories}
        />
        <Books books={currentBooks} />
      </div>
    );
  }
}
const mapStateToProps = (state: any) => ({
  getCategoryStatus: state.book.getCategoryStatus,
  categories: state.book.getCategories,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetCategories: () => dispatch(bookActions.getCategories()),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookShelf);
