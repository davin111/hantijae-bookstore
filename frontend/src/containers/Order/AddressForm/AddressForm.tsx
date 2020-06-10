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
  address1s: any;
  address2: string;
  address2s: any;
  postalCode: string;
  receiverNames: any;
  receiverPhoneNumbers: any;
  signs: any;
  changeFamilyName: (e: any) => any;
  changeGivenName: (e: any) => any;
  changeEmail: (e: any) => any;
  changePhoneNumber: (e: any) => any;
  sameReceiver: boolean;
  sameInfoForBook: any;
  changeSameReceiver: () => any;
  changeSameInfoForBook: (i: number) => any;
  changeReceiverFamilyName: (e: any) => any;
  changeReceiverGivenName: (e: any) => any;
  changeAddress1: (e: any) => any;
  changeAddress1s: () => any;
  changeAddress2: (e: any) => any;
  changeAddress2s: () => any;
  changePostalCode: (e: any) => any;
  changeReceiverNames: () => any;
  changeReceiverPhoneNumbers: () => any;
  changeSigns: () => any;
  confirmed: boolean;
  changeConfirmed: () => any;
  basket: any;
}

interface State {
  sameInfoForBook: any;
  address1s: any;
  address2s: any;
  receiverNames: any;
  receiverPhoneNumbers: any;
  signs: any;
}

// eslint-disable-next-line react/prefer-stateless-function
class AddressForm extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      sameInfoForBook: this.props.sameInfoForBook,
      address1s: this.props.address1s,
      address2s: this.props.address2s,
      receiverNames: this.props.receiverNames,
      receiverPhoneNumbers: this.props.receiverPhoneNumbers,
      signs: this.props.signs,
    };
  }

  changeSameInfoForBook = (i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newSameInfoForBook = this.state.sameInfoForBook;
    newSameInfoForBook[i] = !this.state.sameInfoForBook[i];
    this.setState({
      sameInfoForBook: newSameInfoForBook,
    });
    this.props.changeSameInfoForBook(i);
  };

  changeSigns = (e: any, i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newSigns = this.state.signs;
    newSigns[i] = e.target.value;
    this.setState({
      signs: newSigns,
    });
    this.props.changeSigns();
  };

  changeReceiverNames = (e: any, i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newReceiverNames = this.state.receiverNames;
    newReceiverNames[i] = e.target.value;
    this.setState({
      receiverNames: newReceiverNames,
    });
    this.props.changeReceiverNames();
  };

  changeReceiverPhoneNumbers = (e: any, i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newReceiverPhoneNumbers = this.state.receiverPhoneNumbers;
    newReceiverPhoneNumbers[i] = e.target.value;
    this.setState({
      receiverPhoneNumbers: newReceiverPhoneNumbers,
    });
    this.props.changeReceiverPhoneNumbers();
  };

  changeAddress1s = (e: any, i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newAddress1s = this.state.address1s;
    newAddress1s[i] = e.target.value;
    this.setState({
      address1s: newAddress1s,
    });
    this.props.changeAddress1s();
  };

  changeAddress2s = (e: any, i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newAddress2s = this.state.address2s;
    newAddress2s[i] = e.target.value;
    this.setState({
      address2s: newAddress2s,
    });
    this.props.changeAddress2s();
  };

  makeBookInfoList(count: number) {
    const bookInfoList = [];
    for (let i = 1; i < count; i += 1) {
      let address1Info = null;
      let address2Info = null;
      let receiverPhoneInfo = null;
      let receiverNameInfo = null;
      let signInfo = null;
      if (!this.props.sameInfoForBook[i]) {
        address1Info = (
          <Grid item xs={12}>
            <TextField
              required
              id={`address1${i}`}
              name="address1"
              label="주소"
              helperText="되도록 도로명 주소를 입력해주세요."
              fullWidth
              autoComplete="billing address-line1"
              onChange={(e) => this.changeAddress1s(e, i)}
              value={this.state.address1s[i]}
            />
          </Grid>
        );
        address2Info = (
          <Grid item xs={12} sm={6}>
            <TextField
              id={`address2${i}`}
              name="address2"
              label="상세 주소(건물 이름, 층, 호 등)"
              fullWidth
              autoComplete="billing address-line2"
              onChange={(e) => this.changeAddress2s(e, i)}
              value={this.state.address2s[i]}
            />
          </Grid>
        );
        receiverPhoneInfo = (
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id={`receiverPhonenumber${i}`}
              name="receiverPhonenumber"
              label="휴대전화 번호 (받는 분)"
              helperText=""
              fullWidth
              autoComplete="tel"
              onChange={(e) => this.changeReceiverPhoneNumbers(e, i)}
              value={this.state.receiverPhoneNumbers[i]}
            />
          </Grid>
        );
        receiverNameInfo = (
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id={`receiverFirstName${i}`}
              name="receiverFirstName"
              label="이름 (받는 분)"
              fullWidth
              autoComplete="fname"
              onChange={(e) => this.changeReceiverNames(e, i)}
              value={this.state.receiverNames[i]}
            />
          </Grid>
        );
        signInfo = (
          <Grid item xs={12} sm={6}>
            <TextField
              id={`sign${i}`}
              name="sign"
              label="사인받을 분"
              helperText="받는 분과 다른 경우에만 입력하시면 됩니다."
              fullWidth
              onChange={(e) => this.changeSigns(e, i)}
              value={this.state.signs[i]}
            />
          </Grid>
        );
      }
      bookInfoList.push(
        <Grid container spacing={3} id={`bookinfo${i}`} key={`bookinfo${i}`}>
          <Grid item xs={12}>
            <Typography variant="body1" gutterBottom>
              - - - - - - - - - - - - - - - - - - - - - - - - - - -
            </Typography>
          </Grid>
          <Grid item xs={12}>
            <Typography variant="body1" color="primary" gutterBottom>
              {this.props.basket.books[0].title}
              &nbsp;
              [
              {i + 1}
              ]
            </Typography>
          </Grid>
          <Grid item xs={12}>
            <FormControlLabel
              control={(
                <Checkbox
                  color="secondary"
                  name="sameInfoForBook"
                  checked={this.state.sameInfoForBook[i]}
                  onChange={() => this.changeSameInfoForBook(i)}
                />
              )}
              label="이 책을 바로 위 정보와 동일하게 주문"
            />
          </Grid>
          {address1Info}
          {address2Info}
          {receiverPhoneInfo}
          {receiverNameInfo}
          {signInfo}
        </Grid>,
      );
    }
    return bookInfoList;
  }

  render() {
    // let receiverFamilyNameField = null;
    // let receiverGivenNameField = null;
    // if (!this.props.sameReceiver) {
    //   receiverFamilyNameField = null;
    //   receiverGivenNameField = (
    //     <Grid item xs={12} sm={12}>
    //       <TextField
    //         required
    //         id="receiverFirstName"
    //         name="firstName"
    //         label="이름 (받는 분)"
    //         fullWidth
    //         autoComplete="fname"
    //         onChange={(e) => this.props.changeReceiverGivenName(e)}
    //         value={this.props.receiverGivenName}
    //       />
    //     </Grid>
    //   );
    // }
    const bookCount = this.props.basket.books[0].count;
    const bookInfoList = this.makeBookInfoList(bookCount);

    return (
      <>
        <Typography variant="h6" gutterBottom>
          주문 정보 입력
        </Typography>
        <Typography variant="body2" gutterBottom>
          * 표시가 된 곳만 필수항목입니다.
        </Typography>
        <Grid container spacing={3}>
          <Grid item xs={12} sm={12}>
            <TextField
              required
              id="firstName"
              name="firstName"
              label="이름 (주문하는 분)"
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
              helperText="'-'를 제외하고 입력해주세요."
              onChange={(e) => this.props.changePhoneNumber(e)}
              value={this.props.phoneNumber}
            />
          </Grid>
          {/* <Grid item xs={12}>
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
              label="받는 분이 주문하는 분과 같습니다."
            />
          </Grid> */}
          {/* {receiverFamilyNameField}
          {receiverGivenNameField} */}
          <Grid item xs={12}>
            <Typography variant="body1" color="secondary" gutterBottom>
              주문하는 책 각각에 사인과 배송 정보를 입력할 수 있습니다.
            </Typography>
          </Grid>
          <Grid item xs={12}>
            <Typography variant="body1" color="primary" gutterBottom>
              {this.props.basket.books[0].title}
              &nbsp;
              [
              {1}
              ]
            </Typography>
          </Grid>
          <Grid item xs={12}>
            <TextField
              required
              id="address1"
              name="address1"
              label="주소"
              helperText="되도록 도로명 주소를 입력해주세요."
              fullWidth
              autoComplete="billing address-line1"
              onChange={(e) => this.changeAddress1s(e, 0)}
              value={this.state.address1s[0]}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              id="address2"
              name="address2"
              label="상세 주소(건물 이름, 층, 호 등)"
              fullWidth
              autoComplete="billing address-line2"
              onChange={(e) => this.changeAddress2s(e, 0)}
              value={this.state.address2s[0]}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="receiverPhonenumber"
              name="receiverPhonenumber"
              label="휴대전화 번호 (받는 분)"
              helperText=""
              fullWidth
              autoComplete="tel"
              onChange={(e) => this.changeReceiverPhoneNumbers(e, 0)}
              value={this.state.receiverPhoneNumbers[0]}
            />
          </Grid>
          {/* <TextField
              id="zip"
              name="zip"
              label="우편번호"
              helperText="입력하는 경우 5자리 체계를 이용해주세요."
              fullWidth
              autoComplete="billing postal-code"
              onChange={(e) => this.props.changePostalCode(e)}
              value={this.props.postalCode}
            /> */}
          <Grid item xs={12} sm={6}>
            <TextField
              required
              id="receiverFirstName"
              name="receiverFirstName"
              label="이름 (받는 분)"
              fullWidth
              autoComplete="fname"
              onChange={(e) => this.changeReceiverNames(e, 0)}
              value={this.state.receiverNames[0]}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              id="sign"
              name="sign"
              label="사인받을 분"
              helperText="받는 분과 다른 경우에만 입력하시면 됩니다."
              fullWidth
              onChange={(e) => this.changeSigns(e, 0)}
              value={this.state.signs[0]}
            />
          </Grid>
          {/* <Grid item xs={12}>
            <FormControlLabel
              control={<Checkbox color="secondary" name="saveAddress" value="yes" />}
              checked={this.props.confirmed}
              onChange={() => this.props.changeConfirmed()}
              label="입력한 정보가 모두 맞습니다."
            />
          </Grid> */}
        </Grid>
        {bookInfoList}
      </>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketStatus: state.user.basketStatus,
  // basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  // onGetBasket: () => dispatch(userActions.getBasket()),
});

export default connect(mapStateToProps, mapDispatchToProps)(AddressForm);
