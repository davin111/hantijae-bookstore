import React, { Component, Dispatch, Fragment } from 'react';
import { connect } from 'react-redux';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Grid from '@material-ui/core/Grid';
import Container from '@material-ui/core/Container';

import { userActions } from '../../store/actions';


const styles = (theme: any) => createStyles({
  listItem: {
    padding: theme.spacing(1, 0),
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

  makeOrderList(orders: any) {
    const { classes } = this.props;
    return orders.map((order: any) => (
      <Fragment key={order.id}>
        <hr />
        <List disablePadding>
          {this.makeBookList(order.books)}
          <hr />
          <ListItem className={classes.listItem}>
            <ListItemText primary="정가" />
            <Typography variant="subtitle1" className={classes.total}>
              <del>
                {order.totalPrice}
                원
              </del>
            </Typography>
          </ListItem>
          <ListItem className={classes.listItem}>
            <ListItemText primary="금액" />
            <Typography variant="subtitle1" className={classes.total}>
              {order.maxPrice}
              원
            </Typography>
          </ListItem>
        </List>
        <hr />
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <Typography variant="h6" gutterBottom className={classes.title}>
              주문 정보
            </Typography>
            <Grid container>
              <Grid item xs={6}>
                <Typography gutterBottom>주문하시는 분</Typography>
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
                <Typography gutterBottom>받으시는 분</Typography>
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
              <Typography gutterBottom>
                우편번호:
                {' '}
                {order.postal_code}
              </Typography>
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
                  {order.phoneNumber}
                </Typography>
              </Grid>
            </Grid>
          </Grid>
        </Grid>
      </Fragment>
    ));
  }

  render() {
    const { classes } = this.props;

    let orders = null;
    if (this.props.orders.length > 0) {
      orders = this.makeOrderList(this.props.orders);
    }
    return (
      <Container component="main" fixed maxWidth="xl">
        <main className={classes.layout}>
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
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
  onGetOrders: () => dispatch(userActions.getOrders()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(MyPage));
