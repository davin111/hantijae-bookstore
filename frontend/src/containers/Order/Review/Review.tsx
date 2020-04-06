import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Typography from '@material-ui/core/Typography';
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import Grid from '@material-ui/core/Grid';

import { userStatus } from '../../../constants/constants';
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
  postalCode: string;
  payer: string;
}

class Review extends Component<Props> {
  makeBookList(books: any) {
    const { classes } = this.props;
    return books.map((book: any) => (
      <ListItem className={classes.listItem} key={book.id}>
        <ListItemText primary={book.title} secondary={book.subtitle} />
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
                  {this.props.familyName}
                  {this.props.givenName}
                </Typography>
              </Grid>
            </Grid>
            <Grid container>
              <Grid item xs={6}>
                <Typography gutterBottom>받으시는 분</Typography>
              </Grid>
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {this.props.receiverFamilyName}
                  {this.props.receiverGivenName}
                </Typography>
              </Grid>
            </Grid>
            <Grid item xs={12}>
              <Typography gutterBottom>주소</Typography>
            </Grid>
            <Grid item xs={12}>
              <Typography gutterBottom>{this.props.address1}</Typography>
              <Typography gutterBottom>{this.props.address2}</Typography>
              <Typography gutterBottom>
                우편번호:
                {' '}
                {this.props.postalCode}
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
                <Typography gutterBottom>{this.props.payer}</Typography>
              </Grid>
            </Grid>
            <Grid container justify="center">
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {this.props.email}
                </Typography>
              </Grid>
            </Grid>
            <Grid container justify="center">
              <Grid item xs={6}>
                <Typography gutterBottom>
                  {this.props.phoneNumber}
                </Typography>
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
