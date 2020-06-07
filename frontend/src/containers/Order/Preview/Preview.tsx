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
          {/* <ListItem className={classes.listItem}>
            <ListItemText primary="정가" />
            <Typography variant="subtitle1" className={classes.total}>
              <del>
                {this.props.basket.totalPrice}
                원
              </del>
            </Typography>
          </ListItem> */}
          <ListItem className={classes.listItem}>
            <ListItemText primary="금액" />
            <Typography variant="subtitle1" className={classes.total}>
              {this.props.basket.totalPrice}
              원
            </Typography>
          </ListItem>
          <hr />
          <Typography variant="body1" gutterBottom>
            『당신이 나의 백신입니다』 저자 자필 사인본 이벤트를 진행하고 있습니다!
          </Typography>
          <Typography variant="body2" gutterBottom>
            한티재 온라인 책창고에서 책을 주문하시면, 힘들고 아픈 사람 곁에 늘 함께 있는 선생님의
            <br />
            따뜻한 글씨를 책에 담아 보내드립니다. 많은 신청 부탁드립니다!
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
