import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Grid from '@material-ui/core/Grid';
import Container from '@material-ui/core/Container';

import { userStatus } from '../../constants/constants';
import { userActions } from '../../store/actions';
import './MyPage.css';

const styles = (theme: any) => createStyles({
  listItem: {
    padding: theme.spacing(1, 1),
  },
  total: {
    fontWeight: 700,
  },
  title: {
    marginTop: theme.spacing(2),
  },
});

interface Props {
  me: any;
  orders: any;
  onGetMe: () => any;
  onGetOrders: () => any;
  classes: any;
  getMeStatus: string;
}

class MyPage extends Component<Props> {
  componentDidMount() {
    this.props.onGetMe()
      .then(() => {
        this.props.onGetOrders();
      });
  }

  makeBookList(books: any) {
    const { classes } = this.props;
    return books.map((book: any) => (
      <ListItem className={classes.listItem} key={book.id}>
        <ListItemText primary={book.title} secondary={book.subtitle} />
        <Typography variant="body2">
          {book.count}
          권
        </Typography>
        <Typography variant="body2">
          &nbsp;*&nbsp;
        </Typography>
        <Typography variant="body2">
          {book.full_price}
          원
        </Typography>
      </ListItem>
    ));
  }

  // eslint-disable-next-line class-methods-use-this
  makeBookInfoReviewList(books: any) {
    const bookInfoList = [];
    for (let i = 0; i < books.length; i += 1) {
      const book = books[i];
      let sign = '없음';
      if (book.sign) {
        sign = book.sign;
      }
      bookInfoList.push(
        <Grid item xs={12} id={`bookinforeview${i}`} key={`bookinforeview${i}`}>
          <Typography variant="body1" gutterBottom>
            - - - - - - - - - - - - - - - - - - - - - - - - - - -
          </Typography>
          <Typography variant="body1" color="primary" gutterBottom>
            {book.title}
            &nbsp;
            [
            {i + 1}
            ]
          </Typography>
          <Typography gutterBottom>
            주소:&nbsp;
            {book.address}
          </Typography>
          <Typography gutterBottom>
            휴대전화 번호 (받는 분):&nbsp;
            {book.receiver_phone_number}
          </Typography>
          <Typography gutterBottom>
            이름 (받는 분):&nbsp;
            {book.receiver_name}
          </Typography>
          <Typography gutterBottom>
            사인받을 분:&nbsp;
            {sign}
          </Typography>
          <Typography gutterBottom />
        </Grid>,
      );
    }
    return bookInfoList;
  }

  makeOrderList(orders: any) {
    const { classes } = this.props;
    return orders.map((order: any) => {
      let bookBasketStatus = '책 담는 중';
      let accountInfo = null;
      if (order.status === -1) {
        bookBasketStatus = '유효하지 않음';
      }
      if (order.status === 2) {
        bookBasketStatus = '주문 완료';
        accountInfo = (
          <>
            <Typography variant="body1" gutterBottom>
              다음 계좌로 입금 부탁드립니다.
            </Typography>
            <Typography variant="body1" gutterBottom>
              국민은행 618701-04-129813 오은지(도서출판 한티재)
            </Typography>
          </>
        );
      } else if (order.status === 3) {
        bookBasketStatus = '입금 확인';
      } else if (order.status === 4) {
        bookBasketStatus = '발송 완료';
      } else if (order.status === 5) {
        bookBasketStatus = '수령 확인';
      }

      let bookBasketInfo = '';
      let priceInfo = null;
      let orderInfo = null;
      if (order.info === '2020.04.10YEARS') {
        bookBasketInfo = '한티재 10주년 기념 특판 이벤트';
        priceInfo = (
          <>
            <ListItem className={classes.listItem}>
              <ListItemText primary="정가" />
              <Typography variant="subtitle1" className={classes.total}>
                <del>
                  {order.total_price}
                  원
                </del>
              </Typography>
            </ListItem>
            <ListItem className={classes.listItem}>
              <ListItemText primary="금액" />
              <Typography variant="subtitle1" className={classes.total}>
                {order.max_price}
                원
              </Typography>
            </ListItem>
          </>
        );

        let postalCode = null;
        if (order.postal_code !== '') {
          postalCode = (
            <Typography gutterBottom>
              우편번호:
              {' '}
              {order.postal_code}
            </Typography>
          );
        }
        orderInfo = (
          <>
            <Grid item xs={12} sm={6}>
              <Typography variant="h6" gutterBottom className={classes.title}>
                주문 정보
              </Typography>
              <Grid container>
                <Grid item xs={6}>
                  <Typography gutterBottom>주문하는 분</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.family_name}
                    {order.given_name}
                  </Typography>
                </Grid>
              </Grid>
              <Grid container>
                <Grid item xs={6}>
                  <Typography gutterBottom>받는 분</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.receiver_family_name}
                    {order.receiver_given_name}
                  </Typography>
                </Grid>
              </Grid>
              <Grid item xs={12}>
                <Typography gutterBottom>주소</Typography>
              </Grid>
              <Grid item xs={12}>
                <Typography gutterBottom>{order.address}</Typography>
                {postalCode}
              </Grid>
            </Grid>
            <Grid item container direction="column" xs={12} sm={6}>
              <Typography variant="h6" gutterBottom className={classes.title}>
                계좌 입금 정보
              </Typography>
              <Grid container>
                <Grid item xs={6}>
                  <Typography gutterBottom>입금자 명의</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>{order.payer}</Typography>
                </Grid>
              </Grid>
              <Grid container justify="center">
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.email}
                  </Typography>
                </Grid>
              </Grid>
              <Grid container justify="center">
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.phone_number}
                  </Typography>
                </Grid>
              </Grid>
            </Grid>
          </>
        );
      } else if (order.info === '2020.06.NEWBOOK') {
        bookBasketInfo = '『당신이 나의 백신입니다』 저자 자필 사인본 이벤트';
        priceInfo = (
          <ListItem className={classes.listItem}>
            <ListItemText primary="금액" />
            <Typography variant="subtitle1" className={classes.total}>
              {order.total_price}
              원
            </Typography>
          </ListItem>
        );
        orderInfo = (
          <>
            <Grid item xs={12}>
              <Typography variant="h6" gutterBottom className={classes.title}>
                주문 정보
              </Typography>
              <Grid container>
                <Grid item xs={6}>
                  <Typography gutterBottom>주문하는 분</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.family_name}
                    {order.given_name}
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.email}
                  </Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>
                    {order.phone_number}
                  </Typography>
                </Grid>
              </Grid>
              {this.makeBookInfoReviewList(order.books)}
            </Grid>
            <Grid item container direction="column" xs={12}>
              <Typography variant="h6" gutterBottom className={classes.title}>
                계좌 입금 정보
              </Typography>
              <Grid container>
                <Grid item xs={6}>
                  <Typography gutterBottom>입금자 이름</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography gutterBottom>{order.payer}</Typography>
                </Grid>
              </Grid>
            </Grid>
          </>
        );
      }

      return (
        <div className="OrderElement" key={order.id}>
          <List disablePadding>
            <ListItemText primary="책바구니 번호" />
            <Typography variant="subtitle1" className={classes.total}>
              {order.id}
            </Typography>
            <hr />
            <ListItem className={classes.listItem}>
              <ListItemText primary="정보" />
              <Typography variant="subtitle1" className={classes.total}>
                {bookBasketInfo}
              </Typography>
            </ListItem>
            <ListItem className={classes.listItem}>
              <ListItemText primary="상태" />
              <Typography variant="subtitle1" className={classes.total}>
                {bookBasketStatus}
              </Typography>
            </ListItem>
            {accountInfo}
            <hr />
            {this.makeBookList(order.books)}
            <hr />
            {priceInfo}
          </List>
          <hr />
          <Grid container spacing={2}>
            {orderInfo}
          </Grid>
        </div>
      );
    });
  }

  render() {
    const { classes } = this.props;

    let orders = null;
    if (this.props.orders.length > 0) {
      orders = this.makeOrderList(this.props.orders);
    } else {
      orders = (
        <div>
          <hr />
          <Typography variant="h5" gutterBottom>
            주문 내역이 없습니다. 책을 담으러 가볼까요?
          </Typography>
        </div>
      );
    }

    let username = '';
    let email = '';
    let name = '';
    if (this.props.getMeStatus === userStatus.FAILURE || this.props.me.anonymous === true) {
      username = '비회원';
      email = '비회원';
      name = '비회원';
    } else {
      username = this.props.me.username;
      email = this.props.me.email;
      name = this.props.me.givenName;
    }

    return (
      <Container component="main" fixed maxWidth="md">
        <div className="ForceMargin" />
        <main className={classes.layout}>
          <Typography variant="h6" gutterBottom>
            회원 정보
          </Typography>
          <div className="UserInfo">
            <ListItem className={classes.listItem}>
              <ListItemText primary="아이디" />
              <Typography variant="subtitle1" className={classes.total}>
                {username}
              </Typography>
            </ListItem>
            <ListItem className={classes.listItem}>
              <ListItemText primary="이메일" />
              <Typography variant="subtitle1" className={classes.total}>
                {email}
              </Typography>
            </ListItem>
            <ListItem className={classes.listItem}>
              <ListItemText primary="이름" />
              <Typography variant="subtitle1" className={classes.total}>
                {name}
              </Typography>
            </ListItem>
          </div>
          <Typography variant="h6" gutterBottom>
            주문 내역
          </Typography>
          {orders}
        </main>
      </Container>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  orders: state.user.orders,
  user: state.user.login,
  me: state.user.me,
  getMeStatus: state.user.getMeStatus,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
  onGetOrders: () => dispatch(userActions.getOrders()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(MyPage));
