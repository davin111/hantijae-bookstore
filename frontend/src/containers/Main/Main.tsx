import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import {
  BookShelf, LoginModal, FullBasketModal, BasketInfoModal, EventModal,
} from '../../components';
import { bookActions } from '../../store/actions';
import './Main.css';

interface Props {
  history: any;
  onChangeActiveSeries: (seriesId: number) => any;
  activeSeriesId: number;
}

class Main extends Component<Props> {
  componentDidMount() {
    // const { onGetBooks } = this.props;
    // onGetBooks();
  }

  render() {
    let { activeSeriesId } = this.props;
    if (activeSeriesId <= 0) {
      const max = 6;
      const min = 1;
      activeSeriesId = Math.floor(Math.random() * (max - min)) + min;
      this.props.onChangeActiveSeries(activeSeriesId);
    }
    return (
      <div>
        <BookShelf
          history={this.props.history}
          seriesId={activeSeriesId}
        />
        <LoginModal history={this.props.history} />
        <FullBasketModal history={this.props.history} />
        <BasketInfoModal history={this.props.history} />
        {/* <EventModal history={this.props.history} /> */}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  books: state.book.books,
  activeSeriesId: state.book.activeSeriesId,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBooks: () => dispatch(bookActions.getBooks()),
  onChangeActiveSeries: (seriesId: number) => dispatch(bookActions.changeActiveSeries(seriesId)),
});

export default connect(mapStateToProps, mapDispatchToProps)(Main);
