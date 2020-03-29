import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './BookShelf.css';
import NavigationPanel from '../Nav/NavigationPanel/NavigationPanel';
import Books from '../Books/Books';
import { seriesStatus } from '../../constants/constants';

interface Props{
  categories: any;
  getCategoryStatus: string;
  onGetCategories: () => any;
  series: any;
  getSeriesStatus: string;
  onGetAllSeries: () => any;
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
    // this.props.onGetCategories();
    this.props.onGetAllSeries()
      .then(() => {
        let activeTab = '';
        if (this.props.getSeriesStatus === seriesStatus.SUCCESS) {
          activeTab = this.props.series[0].name;
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
    for (let i = 0; i < this.props.series.length; i += 1) {
      if (this.props.series[i].name === this.state.activeTab) {
        currentBooks = this.props.series[i].books;
        break;
      }
    }

    return (
      <div className="BookShelf">
        <NavigationPanel
          onMainFilterClick={this.onTabChange}
          activeTab={this.state.activeTab}
          categories={this.props.series}
        />
        <Books books={currentBooks} />
      </div>
    );
  }
}
const mapStateToProps = (state: any) => ({
  getCategoryStatus: state.book.getCategoryStatus,
  categories: state.book.getCategories,
  getSeriesStatus: state.book.getSeriesStatus,
  series: state.book.getAllSeries,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetCategories: () => dispatch(bookActions.getCategories()),
  onGetAllSeries: () => dispatch(bookActions.getAllSeries()),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookShelf);
