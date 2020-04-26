import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import {
  BookShelf, LoginModal, FullBasketModal, BasketInfoModal, EventModal,
} from '../../components';
import { bookActions } from '../../store/actions';
import './Main.css';

interface Props {
  history: any;
}

class Main extends Component<Props> {
  componentDidMount() {
    // const { onGetBooks } = this.props;
    // onGetBooks();
  }

  render() {
    let activeSeriesId = 0;
    if (this.props.history.location.pathname.startsWith('/series=')) {
      activeSeriesId = this.props.history.location.pathname.split('=')[1];
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
        <EventModal history={this.props.history} />
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  books: state.book.books,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBooks: () => dispatch(bookActions.getBooks()),
});

export default connect(mapStateToProps, mapDispatchToProps)(Main);
