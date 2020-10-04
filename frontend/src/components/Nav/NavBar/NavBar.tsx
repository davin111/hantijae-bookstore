import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../../store/actions';
import './NavBar.css';

interface Props{
  series: any;
  history: any;
  getSeriesStatus: string;
  onGetAllSeries: () => any;
  onChangeActiveSeries: (seriesId: number) => any;
  activeSeriesId: number;
}

interface State{
  activeSeriesId: number;
}

class NavBar extends Component<Props, State> {
  componentDidMount() {
    this.props.onGetAllSeries();
  }

  clickSeriesHandler(id: number) {
    this.props.history.push(`/series=${id}`);
    this.props.onChangeActiveSeries(id);
  }

  render() {
    let series = null;
    if (this.props.series.length > 0) {
      const { activeSeriesId } = this.props;

      series = this.props.series.map((oneSeries: any) => (
        <button
          type="button"
          key={`${oneSeries.id} ${activeSeriesId}`}
          onClick={() => this.clickSeriesHandler(oneSeries.id)}
          className={`CategoryButton ${oneSeries.id === Number(activeSeriesId) ? 'CategoryButtonActive' : ''}`}
        >
          {oneSeries.name}
        </button>
      ));
    }
    return (
      <div className="NavBar">
        <button
          type="button"
          key={-2}
          onClick={() => {
            this.props.history.push('/hantijae');
            this.props.onChangeActiveSeries(-2);
          }}
          className={`CategoryButton ${(this.props.history.location.pathname === '/hantijae') ? 'CategoryButtonActive' : ''}`}
        >
          한티재
        </button>
        {series}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getSeriesStatus: state.book.getSeriesStatus,
  series: state.book.getAllSeries,
  activeSeriesId: state.book.activeSeriesId,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetAllSeries: () => dispatch(bookActions.getAllSeries()),
  onChangeActiveSeries: (seriesId: number) => dispatch(bookActions.changeActiveSeries(seriesId)),
});

export default connect(mapStateToProps, mapDispatchToProps)(NavBar);
