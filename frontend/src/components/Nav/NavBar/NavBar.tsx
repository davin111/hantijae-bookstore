import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../../store/actions';
import './NavBar.css';

interface Props{
  series: any;
  history: any;
  getSeriesStatus: string;
  onGetAllSeries: () => any;
}

interface State{
  activeSeriesId: number;
}

class NavBar extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      activeSeriesId: 0,
    };
  }

  componentDidMount() {
    this.props.onGetAllSeries();
  }

  /* eslint-disable react/no-did-update-set-state */
  componentDidUpdate(prevProps: Props) {
    if (this.props.history !== prevProps.history) {
      this.setState({ activeSeriesId: 0 });
    }
  }
  /* eslint-enable react/no-did-update-set-state */

  clickSeriesHandler(id: number) {
    this.props.history.push(`/series=${id}`);
    this.setState({ activeSeriesId: id });
  }

  render() {
    let series = null;
    if (this.props.series.length > 0) {
      let activeSeriesId = 0;
      const { pathname } = this.props.history.location;
      if (pathname.startsWith('/series=')) {
        activeSeriesId = pathname.split('=')[1];
      } else if (pathname === '/') {
        activeSeriesId = this.props.series[0].id;
      } else {
        activeSeriesId = this.state.activeSeriesId;
      }

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
            this.setState({ activeSeriesId: -2 });
          }}
          className={`CategoryButton ${this.props.history.location.pathname === '/hantijae' ? 'CategoryButtonActive' : ''}`}
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
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetAllSeries: () => dispatch(bookActions.getAllSeries()),
});

export default connect(mapStateToProps, mapDispatchToProps)(NavBar);
