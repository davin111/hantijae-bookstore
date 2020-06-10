import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Grid from '@material-ui/core/Grid';

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
  familyName: string;
  givenName: string;
  email: string;
  phoneNumber: string;
  receiverFamilyName: string;
  receiverGivenName: string;
  address1: string;
  address2: string;
  addresses: any;
  receiverNames: any;
  receiverPhoneNumbers: any;
  signs: any;
  postalCode: string;
  payer: string;
  sameReceiver: boolean;
}

class Review extends Component<Props> {
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

  makeBookInfoReviewList(count: number) {
    const bookInfoList = [];
    for (let i = 0; i < count; i += 1) {
      let sign = '없음';
      if (this.props.signs[i]) {
        sign = this.props.signs[i];
      }
      bookInfoList.push(
        <Grid item xs={12} id={`bookinforeview${i}`} key={`bookinforeview${i}`}>
          <Typography variant="body1" gutterBottom>
            - - - - - - - - - - - - - - - - - - - - - - - - - - -
          </Typography>
          <Typography variant="body1" color="primary" gutterBottom>
            {this.props.basket.books[0].title}
            &nbsp;
            [
            {i + 1}
            ]
          </Typography>
          <Typography gutterBottom>
            주소:&nbsp;
            {this.props.addresses[i]}
          </Typography>
          {/* {postalCode} */}
          <Typography gutterBottom>
            휴대전화 번호 (받는 분):&nbsp;
            {this.props.receiverPhoneNumbers[i]}
          </Typography>
          <Typography gutterBottom>
            이름 (받는 분):&nbsp;
            {this.props.receiverNames[i]}
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

  render() {
    const { classes } = this.props;

    // let receiverFamilyName = this.props.familyName;
    // let receiverGivenName = this.props.givenName;
    // if (!this.props.sameReceiver) {
    //   receiverFamilyName = this.props.receiverFamilyName;
    //   receiverGivenName = this.props.receiverGivenName;
    // }

    // let postalCode = null;
    // if (this.props.postalCode !== '') {
    //   postalCode = (
    //     <Typography gutterBottom>
    //       우편번호:
    //       {' '}
    //       {this.props.postalCode}
    //     </Typography>
    //   );
    // }

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
        </List>
        <hr />
        <Grid container spacing={2}>
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
                  {this.props.familyName}
                  {this.props.givenName}
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {this.props.email}
                </Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {this.props.phoneNumber}
                </Typography>
              </Grid>
            </Grid>
            {/* <Grid container>
              <Grid item xs={6}>
                <Typography gutterBottom>받는 분</Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {receiverFamilyName}
                  {receiverGivenName}
                </Typography>
              </Grid>
            </Grid> */}
            {this.makeBookInfoReviewList(this.props.basket.books[0].count)}
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
                <Typography gutterBottom>{this.props.payer}</Typography>
              </Grid>
            </Grid>
          </Grid>
        </Grid>
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

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Review));
