import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';

import { userActions } from '../../../store/actions';


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
  classes: any;
  basket: any;
}

class Preview extends Component<Props> {
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

  render() {
    const { classes } = this.props;

    return (
      <>
        <Typography variant="h6" gutterBottom>
          책바구니 내역 확인
        </Typography>
        <List disablePadding>
          {this.makeBookList(this.props.basket.books)}
          <hr />
          <ListItem className={classes.listItem}>
            <ListItemText primary="정가" />
            <Typography variant="subtitle1" className={classes.total}>
              <del>
                {this.props.basket.totalPrice}
                원
              </del>
            </Typography>
          </ListItem>
          <ListItem className={classes.listItem}>
            <ListItemText primary="금액" />
            <Typography variant="subtitle1" className={classes.total}>
              {this.props.basket.maxPrice}
              원
            </Typography>
          </ListItem>
          <hr />
          <Typography variant="body1" gutterBottom>
            한티재 10주년 기념 ‘10권 10만 원 책바구니’ 특판 이벤트를 진행하고 있습니다!
          </Typography>
          <Typography variant="body2" gutterBottom>
            책의 정가와 상관 없이 한티재 책 최대 10권을 10만 원에 구입하실 수 있습니다.
            <br />
            단, 10권보다 적게 담거나, 정가 총액이 10만 원보다 적어도 결제 금액은 10만 원입니다^^
          </Typography>
        </List>
      </>
    );
  }
}

const mapStateToProps = (state: any) => ({
  loginStatus: state.user.loginStatus,
  user: state.user.login,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onLogin: (username: string, password: string) => dispatch(userActions.login(username, password)),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Preview));
