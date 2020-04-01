import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './BookShelf.css';
import Books from '../Books/Books';


interface Props{
  series: any;
  allSeries: any;
  getSeriesStatus: string;
  onGetSeries: (id: number) => any;
  history: any;
  seriesId: number;
}
interface State{
  series: any;
}

class BookShelf extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      series: null,
    };
  }

  componentDidMount() {
    this.refreshBookShelf();
  }

  componentDidUpdate(prevProps: Props) {
    if ((Object.keys(prevProps.allSeries).length === 0
        && this.props.allSeries !== prevProps.allSeries)
        || this.props.seriesId !== prevProps.seriesId) {
      this.refreshBookShelf();
    }
  }

  refreshBookShelf() {
    if (Object.keys(this.props.allSeries).length !== 0) {
      let activeSeriesId = 0;
      if (this.props.seriesId === 0) {
        activeSeriesId = this.props.allSeries[0].id;
      } else {
        activeSeriesId = this.props.seriesId;
      }

      this.props.onGetSeries(activeSeriesId)
        .then(() => {
          this.setState({ series: this.props.series });
        });
    }
  }

  render() {
    let books = null;
    if (this.state.series != null) {
      books = <Books books={this.state.series.books} history={this.props.history} />;
    }
    return (
      <div className="BookShelf">
        {books}
      </div>
    );
  }
}
const mapStateToProps = (state: any) => ({
  getSeriesStatus: state.book.getSeriesStatus,
  series: state.book.getSeries,
  allSeries: state.book.getAllSeries,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetSeries: (id: number) => dispatch(bookActions.getSeries(id)),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookShelf);
