import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Grid from '@material-ui/core/Grid';
import Typography from '@material-ui/core/Typography';
import TextField from '@material-ui/core/TextField';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Checkbox from '@material-ui/core/Checkbox';

interface Props {
  familyName: string;
  givenName: string;
  email: string;
  phoneNumber: string;
  receiverFamilyName: string;
  receiverGivenName: string;
  address1: string;
  address2: string;
  postalCode: string;
  changeFamilyName: (e: any) => any;
  changeGivenName: (e: any) => any;
  changeEmail: (e: any) => any;
  changePhoneNumber: (e: any) => any;
  sameReceiver: boolean;
  changeSameReceiver: () => any;
  changeReceiverFamilyName: (e: any) => any;
  changeReceiverGivenName: (e: any) => any;
  changeAddress1: (e: any) => any;
  changeAddress2: (e: any) => any;
  changePostalCode: (e: any) => any;
  confirmed: boolean;
  changeConfirmed: () => any;
}

class AddressForm extends Component<Props> {
  render() {
    let receiverFamilyNameField = null;
    let receiverGivenNameField = null;
    if (!this.props.sameReceiver) {
      receiverFamilyNameField = (
        <Grid item xs={12} sm={6}>
          <TextField
            required
            id="receiverLastName"
            name="lastName"
            label="성 (받으시는 분)"
            fullWidth
            autoComplete="lname"
            onChange={(e) => this.props.changeReceiverFamilyName(e)}
            value={this.props.receiverFamilyName}
          />
        </Grid>
      );
      receiverGivenNameField = (
        <Grid item xs={12} sm={6}>
          <TextField
            required
            id="receiverFirstName"
            name="firstName"
            label="이름 (받으시는 분)"
            fullWidth
            autoComplete="fname"
            onChange={(e) => this.props.changeReceiverGivenName(e)}
            value={this.props.receiverGivenName}
          />
        </Grid>
      );
    }


    return (
      <>
        <Typography variant="h6" gutterBottom>
          주문 정보 입력
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="lastName"
              name="lastName"
              label="성 (주문하시는 분)"
              fullWidth
              autoComplete="lname"
              onChange={(e) => this.props.changeFamilyName(e)}
              value={this.props.familyName}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="firstName"
              name="firstName"
              label="이름 (주문하시는 분)"
              fullWidth
              autoComplete="fname"
              onChange={(e) => this.props.changeGivenName(e)}
              value={this.props.givenName}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              fullWidth
              id="email"
              label="이메일"
              name="email"
              autoComplete="email"
              onChange={(e) => this.props.changeEmail(e)}
              value={this.props.email}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="phonenumber"
              name="phonenumber"
              label="휴대전화 번호"
              fullWidth
              autoComplete="tel"
              onChange={(e) => this.props.changePhoneNumber(e)}
              value={this.props.phoneNumber}
            />
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={(
                <Checkbox
                  color="secondary"
                  name="saveAddress"
                  value="yes"
                  checked={this.props.sameReceiver}
                  onChange={() => this.props.changeSameReceiver()}
                />
              )}
              label="받으시는 분이 주문하시는 분과 같습니다."
            />
          </Grid>
          {receiverFamilyNameField}
          {receiverGivenNameField}
          <Grid item xs={12}>
            <TextField
              required
              id="address1"
              name="address1"
              label="주소"
              helperText="가급적 도로명 주소를 사용해주세요."
              fullWidth
              autoComplete="billing address-line1"
              onChange={(e) => this.props.changeAddress1(e)}
              value={this.props.address1}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              id="address2"
              name="address2"
              label="상세주소(건물 이름, 층, 호 등)"
              fullWidth
              autoComplete="billing address-line2"
              onChange={(e) => this.props.changeAddress2(e)}
              value={this.props.address2}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="zip"
              name="zip"
              label="우편번호"
              fullWidth
              autoComplete="billing postal-code"
              onChange={(e) => this.props.changePostalCode(e)}
              value={this.props.postalCode}
            />
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={<Checkbox color="secondary" name="saveAddress" value="yes" />}
              checked={this.props.confirmed}
              onChange={() => this.props.changeConfirmed()}
              label="위의 정보가 정확함을 확인했습니다."
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

export default connect(mapStateToProps, mapDispatchToProps)(AddressForm);
