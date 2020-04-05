import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { bookActions } from '../../store/actions';
import './BookDetail.css';

interface Props {
  location: any;
  book: any;
  getBookStatus: string;
  onGetBook: (id: number) => any;
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
    let authors = null;
    let desc = '';
    let img = null;
    if (Object.keys(this.state.book).length > 0) {
      authors = this.state.book.authors.map(
        (author: any) => (
          <p className="Authors" key={author.id}>
            {author.name}
          </p>
        ),
      );

      desc = this.state.book.description.split('\n').map((line: string) => (
        <span>
          {line}
          <br />
        </span>
      ));
      /* eslint-disable-next-line */
      img = <img src={require(`./book_covers_3d/${this.state.book.title.replace(':', '').replace('!', '')}.png`)} />;
    }

    const { book } = this.props;

    return (
      <div>
        <div className="BookDetail">
          <div className="BookCoverStand">
            {img}
          </div>
          <div className="BookDetailInfo">
            <h1 id="title">{book.title}</h1>
            <h1 id="subtitle">{book.subtitle}</h1>
            {authors}
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
            </div>
          </div>
        </div>
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
