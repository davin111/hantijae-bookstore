import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Typography from '@material-ui/core/Typography';
import Grid from '@material-ui/core/Grid';
import TextField from '@material-ui/core/TextField';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Checkbox from '@material-ui/core/Checkbox';

interface Props{
  changePayer: (e: any) => any;
  confirmed2: boolean;
  changeConfirmed2: () => any;
  payer: string;
}

class PaymentForm extends Component<Props> {
  render() {
    return (
      <>
        <Typography variant="h6" gutterBottom>
          계좌 입금 정보
        </Typography>
        <Typography variant="body1" color="secondary" gutterBottom>
          입금할 계좌는 주문하기가 완료된 후 알려드리겠습니다.
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <TextField
              required
              id="lastName"
              name="lastName"
              label="입금자 이름"
              fullWidth
              autoComplete="lname"
              onChange={(e) => this.props.changePayer(e)}
              value={this.props.payer}
            />
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={<Checkbox color="secondary" name="saveCard" value="yes" />}
              label="입금 확인 후 배송해 드리겠습니다."
              checked={this.props.confirmed2}
              onChange={() => this.props.changeConfirmed2()}
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
