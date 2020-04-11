import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './BookDetail.css';
import {
  BookCountWithCart, LoginModal, FullBasketModal, BasketInfoModal,
} from '../../components';

interface Props {
  location: any;
  book: any;
  getBookStatus: string;
  onGetBook: (id: number) => any;
  history: any;
}

interface State {
  book: any;
}

class BookDetail extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      book: {},
    };
  }

  componentDidMount() {
    window.scrollTo(0, 0);
    this.props.onGetBook(this.props.location.pathname.split('=')[1])
      .then(() => this.setState({ book: this.props.book }));
  }

  render() {
    let authorStr = '';
    let desc = '';
    let img = null;
    let bookCart = null;
    if (Object.keys(this.state.book).length > 0) {
      const authorNames = [];
      for (let i = 0; i < this.state.book.authors.length; i += 1) {
        authorNames.push(this.state.book.authors[i].name);
      }
      authorStr = authorNames.join(' · ');

      desc = this.state.book.description.split('\n').map((line: string) => (
        <span>
          {line}
          <br />
        </span>
      ));
      /* eslint-disable-next-line */
      img = <img src={require(`./book_covers_3d/${this.state.book.title.replace(':', '').replace('!', '')}.png`)} />;

      if (this.state.book.visible) {
        if (this.state.book.published_date.split('-')[0] === '2020') {
          bookCart = (
            <h3 className="DetailNotAcceptable">
              특판 이벤트에서 올해 나온 신간은 제외됩니다
            </h3>
          );
        } else {
          bookCart = (
            <div className="DetailCart">
              <BookCountWithCart bookId={this.state.book.id} history={this.props.history} />
            </div>
          );
        }
      } else {
        bookCart = <h3 className="DetailNotVisible">절판</h3>;
      }
    }


    const { book } = this.props;

    return (
      <div>
        <div className="BookDetailUpper">
          <div className="BookCoverStand">
            {img}
          </div>
          <div className="BookDetailInfo">
            <h1 id="title">{book.title}</h1>
            <h1 id="subtitle">{book.subtitle}</h1>
            <h3 id="authors">{authorStr}</h3>
            {/* <Rate rate={this.props.rate} voters={this.props.voters} textColor="#607D8B" /> */}
            <div className="BookDetailInfoList">
              <div className="InfoItem">
                <div className="LItem">가격</div>
                <div className="RItem">
                  {book.full_price}
                  원
                </div>
              </div>
              <div className="InfoItem">
                <div className="LItem">발행일</div>
                <div className="RItem">{book.published_date}</div>
              </div>
              <div className="InfoItem">
                <div className="LItem">
                  쪽수
                </div>
                <div className="RItem">
                  {book.page_count}
                  쪽
                </div>
              </div>
              <div className="InfoItem">
                <div className="LItem">
                  판형
                </div>
                <div className="RItem">
                  {book.size}
                </div>
              </div>
              <div className="InfoItem">
                <div className="LItem">
                  ISBN
                </div>
                <div className="RItem">
                  {book.isbn}
                </div>
              </div>
              {bookCart}
            </div>
          </div>
        </div>
        <LoginModal history={this.props.history} />
        <FullBasketModal history={this.props.history} />
        <BasketInfoModal history={this.props.history} />
        <div className="BookDescriptions">
          <p>
            {desc}
          </p>
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getBookStatus: state.book.getBookStatus,
  book: state.book.getBook,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBook: (id: number) => dispatch(bookActions.getBook(id)),
});

export default connect(mapStateToProps, mapDispatchToProps)(BookDetail);
