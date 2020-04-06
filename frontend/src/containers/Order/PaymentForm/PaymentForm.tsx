import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Typography from '@material-ui/core/Typography';
import Grid from '@material-ui/core/Grid';
import TextField from '@material-ui/core/TextField';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Checkbox from '@material-ui/core/Checkbox';

interface Props{
  changePayer: (e: any) => any;
}

class PaymentForm extends Component<Props> {
  render() {
    return (
      <>
        <Typography variant="h6" gutterBottom>
          계좌 입금 정보
        </Typography>
        <Typography variant="body1" gutterBottom>
          국민은행 618701-04-129813 오은지(도서출판 한티재)
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <TextField
              required
              id="lastName"
              name="lastName"
              label="입금자 명의"
              fullWidth
              autoComplete="lname"
              onChange={(e) => this.props.changePayer(e)}
            />
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={<Checkbox color="secondary" name="saveCard" value="yes" />}
              label="입금 확인 후 배송해 드리겠습니다."
            />
          </Grid>
        </Grid>
      </>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  // onGetBasket: () => dispatch(userActions.getBasket()),
});

export default connect(mapStateToProps, mapDispatchToProps)(PaymentForm);
