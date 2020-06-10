import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Paper from '@material-ui/core/Paper';
import Stepper from '@material-ui/core/Stepper';
import Step from '@material-ui/core/Step';
import StepLabel from '@material-ui/core/StepLabel';
import Button from '@material-ui/core/Button';
import Link from '@material-ui/core/Link';
import Typography from '@material-ui/core/Typography';
import { createStyles, withStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';

import { userStatus, basketStatus } from '../../constants/constants';
import { userActions } from '../../store/actions';
import AddressForm from './AddressForm/AddressForm';
import PaymentForm from './PaymentForm/PaymentForm';
import Review from './Review/Review';
import Preview from './Preview/Preview';

function Copyright() {
  return (
    <Typography variant="body2" color="textSecondary" align="center">
      {'Copyright © '}
      <Link color="inherit" href="http://hantijae-bookstore.com/">
        Hantijae publisher.
      </Link>
      {' '}
      {new Date().getFullYear()}
    </Typography>
  );
}

const styles = (theme: any) => createStyles({
  appBar: {
    position: 'relative',
  },
  layout: {
    width: 'auto',
    // marginLeft: theme.spacing(2),
    // marginRight: theme.spacing(2),
    [theme.breakpoints.up(600 + theme.spacing(2) * 2)]: {
      width: 600,
      marginLeft: 'auto',
      marginRight: 'auto',
    },
  },
  paper: {
    marginTop: theme.spacing(3),
    marginBottom: theme.spacing(3),
    padding: theme.spacing(1),
    [theme.breakpoints.up(600 + theme.spacing(3) * 2)]: {
      marginTop: theme.spacing(6),
      marginBottom: theme.spacing(6),
      padding: theme.spacing(3),
    },
  },
  stepper: {
    padding: theme.spacing(3, 0, 5),
  },
  buttons: {
    display: 'flex',
    justifyContent: 'flex-end',
  },
  button: {
    marginTop: theme.spacing(3),
    marginLeft: theme.spacing(1),
  },
});

interface Props {
  history: any;
  classes: any;
  basketStatus: string;
  basket: any;
  onGetMe: () => any;
  getMeStatus: string;
  me: any;
  onGetBasket202006NewBook: () => any;
  onOrderBasket202006NewBook: (basketId: number, name: string,
    email: string, phoneNumber: string,
    addresses: any, receiverPhoneNumbers: any, receiverNames: any,
    signs: any, payer: string) => any;
}

interface State {
  activeStep: number;
  familyName: string;
  givenName: string;
  email: string;
  phoneNumber: string;
  sameReceiver: boolean;
  sameInfoForBook: any;
  receiverFamilyName: string;
  receiverGivenName: string;
  address1: string;
  address1s: any;
  address2: string;
  address2s: any;
  addresses: any;
  postalCode: string;
  receiverNames: any;
  receiverPhoneNumbers: any;
  signs: any;
  confirmed: boolean;
  confirmed2: boolean;
  payer: string;
}

const steps = ['주문 정보 입력', '계좌 입금 정보', '책바구니 내역 확인'];

class Order extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      activeStep: -1,
      familyName: '',
      givenName: '',
      email: '',
      phoneNumber: '',
      sameReceiver: true,
      sameInfoForBook: {},
      receiverFamilyName: '',
      receiverGivenName: '',
      address1: '',
      address1s: {},
      address2: '',
      address2s: {},
      addresses: {},
      postalCode: '',
      receiverNames: {},
      receiverPhoneNumbers: {},
      signs: {},
      confirmed: false,
      payer: '',
      confirmed2: false,
    };
  }

  componentDidMount() {
    window.scrollTo(0, 0);
    this.props.onGetMe()
      .then(() => {
        if (this.props.getMeStatus === userStatus.SUCCESS) {
          this.setState({
            familyName: this.props.me.familyName,
            givenName: this.props.me.givenName,
            email: this.props.me.email,
          });
        }
      });
    this.props.onGetBasket202006NewBook()
      .then(() => {
        if (this.props.basket.books.length === 0) {
          this.props.history.push('/');
        } else {
          this.setSameInfoForBook(this.props.basket.books[0].count);
        }
      });
  }

  handleNext = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const step = this.state.activeStep;
    const newAddress1s = this.state.address1s;
    const newAddress2s = this.state.address2s;
    const newReceiverNames = this.state.receiverNames;
    const newReceiverPhoneNumbers = this.state.receiverPhoneNumbers;
    const newSigns = this.state.signs;
    const { addresses } = this.state;
    if (step === 1) {
      for (let i = 0; i < Object.keys(this.state.sameInfoForBook).length; i += 1) {
        if (this.state.sameInfoForBook[i]) {
          newAddress1s[i] = newAddress1s[i - 1];
          newAddress2s[i] = newAddress2s[i - 1];
          newReceiverNames[i] = newReceiverNames[i - 1];
          newReceiverPhoneNumbers[i] = newReceiverPhoneNumbers[i - 1];
          newSigns[i] = newSigns[i - 1];
        } else if (!(i in newSigns) || newSigns[i] === '') {
          newSigns[i] = newReceiverNames[i];
        }
        if (!(i in newAddress2s) || newAddress2s[i] === '') {
          addresses[i] = newAddress1s[i];
          newAddress2s[i] = '';
        } else {
          addresses[i] = [newAddress1s[i], newAddress2s[i]].join(', ');
        }
      }
      this.setState({
        address1s: newAddress1s,
        address2s: newAddress2s,
        receiverNames: newReceiverNames,
        receiverPhoneNumbers: newReceiverPhoneNumbers,
        signs: newSigns,
        addresses,
      });
    }

    if (step === 2) {
      // let receiverFamilyName = this.state.familyName;
      // let receiverGivenName = this.state.givenName;
      // if (!this.state.sameReceiver) {
      //   receiverFamilyName = this.state.receiverFamilyName;
      //   receiverGivenName = this.state.receiverGivenName;
      // }

      // let address = this.state.address1;
      // if (this.state.address2 !== '') {
      //   address = [this.state.address1, this.state.address2].join(', ');
      // }

      this.props.onOrderBasket202006NewBook(
        this.props.basket.id,
        this.state.givenName,
        this.state.email,
        this.state.phoneNumber,
        this.state.addresses,
        this.state.receiverPhoneNumbers,
        this.state.receiverNames,
        this.state.signs,
        this.state.payer,
      ).then(() => {
        if (this.props.basketStatus === basketStatus.SUCCESS) {
          this.setState({ activeStep: step + 1 });
          this.props.onGetBasket202006NewBook();
        }
      });
    } else {
      this.setState({ activeStep: step + 1 });
    }
  };

  handleBack = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const step = this.state.activeStep;
    this.setState({ activeStep: step - 1 });
  };

  getStepContent = (step: number) => {
    switch (step) {
      case -1:
        return (
          <Preview basket={this.props.basket} />
        );
      case 0:
        return (
          <AddressForm
            familyName={this.state.familyName}
            givenName={this.state.givenName}
            email={this.state.email}
            phoneNumber={this.state.phoneNumber}
            receiverFamilyName={this.state.receiverFamilyName}
            receiverGivenName={this.state.receiverGivenName}
            address1={this.state.address1}
            address1s={this.state.address1s}
            address2={this.state.address2}
            address2s={this.state.address2s}
            postalCode={this.state.postalCode}
            receiverNames={this.state.receiverNames}
            receiverPhoneNumbers={this.state.receiverPhoneNumbers}
            signs={this.state.signs}
            changeFamilyName={this.changeFamilyName}
            changeGivenName={this.changeGivenName}
            changeEmail={this.changeEmail}
            changePhoneNumber={this.changePhoneNumber}
            sameReceiver={this.state.sameReceiver}
            sameInfoForBook={this.state.sameInfoForBook}
            changeSameReceiver={this.changeSameReceiver}
            changeSameInfoForBook={this.changeSameInfoForBook}
            changeReceiverFamilyName={this.changeReceiverFamilyName}
            changeReceiverGivenName={this.changeReceiverGivenName}
            changeAddress1={this.changeAddress1}
            changeAddress1s={this.changeAddress1s}
            changeAddress2={this.changeAddress2}
            changeAddress2s={this.changeAddress2s}
            changePostalCode={this.changePostalCode}
            changeReceiverNames={this.changeReceiverNames}
            changeReceiverPhoneNumbers={this.changeReceiverPhoneNumbers}
            changeSigns={this.changeSigns}
            confirmed={this.state.confirmed}
            changeConfirmed={this.changeConfirmed}
            basket={this.props.basket}
          />
        );
      case 1:
        return (
          <PaymentForm
            changePayer={this.changePayer}
            confirmed2={this.state.confirmed2}
            changeConfirmed2={this.changeConfirmed2}
            payer={this.state.payer}
          />
        );
      case 2:
        return (
          <Review
            basket={this.props.basket}
            familyName={this.state.familyName}
            givenName={this.state.givenName}
            email={this.state.email}
            phoneNumber={this.state.phoneNumber}
            receiverFamilyName={this.state.receiverFamilyName}
            receiverGivenName={this.state.receiverGivenName}
            address1={this.state.address1}
            address2={this.state.address2}
            addresses={this.state.addresses}
            receiverNames={this.state.receiverNames}
            receiverPhoneNumbers={this.state.receiverPhoneNumbers}
            signs={this.state.signs}
            postalCode={this.state.postalCode}
            payer={this.state.payer}
            sameReceiver={this.state.sameReceiver}
          />
        );
      default:
        throw new Error('Unknown step');
    }
  };

  changeFamilyName = (e: any) => {
    this.setState({ familyName: e.target.value });
  };

  changeGivenName = (e: any) => {
    this.setState({ givenName: e.target.value });
  };

  changeEmail = (e: any) => {
    this.setState({ email: e.target.value });
  };

  changePhoneNumber = (e: any) => {
    this.setState({ phoneNumber: e.target.value });
  };

  changeSameReceiver = () => {
    const checked = this.state.sameReceiver;
    this.setState({ sameReceiver: !checked });
  };

  setSameInfoForBook = (count: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const { sameInfoForBook } = this.state;
    sameInfoForBook[0] = false;
    for (let i = 1; i < count; i += 1) {
      sameInfoForBook[i] = true;
    }
    this.setState({
      sameInfoForBook,
    });
  };

  changeSameInfoForBook = (i: number) => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newSameInfoForBook = this.state.sameInfoForBook;
    this.setState({
      sameInfoForBook: newSameInfoForBook,
    });
  };

  changeReceiverFamilyName = (e: any) => {
    this.setState({ receiverFamilyName: e.target.value });
  };

  changeReceiverGivenName = (e: any) => {
    this.setState({ receiverGivenName: e.target.value });
  };

  changeAddress1 = (e: any) => {
    this.setState({ address1: e.target.value });
  };

  changeAddress1s = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newAddress1s = this.state.address1s;
    this.setState({
      address1s: newAddress1s,
    });
  };

  changeAddress2s = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newAddress2s = this.state.address2s;
    this.setState({
      address2s: newAddress2s,
    });
  };

  changeAddress2 = (e: any) => {
    this.setState({ address2: e.target.value });
  };

  changePostalCode = (e: any) => {
    this.setState({ postalCode: e.target.value });
  };

  changeReceiverNames = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newReceiverNames = this.state.receiverNames;
    this.setState({
      receiverNames: newReceiverNames,
    });
  };

  changeReceiverPhoneNumbers = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newReceiverPhoneNumbers = this.state.receiverPhoneNumbers;
    this.setState({
      receiverPhoneNumbers: newReceiverPhoneNumbers,
    });
  };

  changeSigns = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const newSigns = this.state.signs;
    this.setState({
      signs: newSigns,
    });
  };

  changeConfirmed = () => {
    const checked = this.state.confirmed;
    this.setState({ confirmed: !checked });
  };

  changePayer = (e: any) => {
    this.setState({ payer: e.target.value });
  };

  changeConfirmed2 = () => {
    const checked = this.state.confirmed2;
    this.setState({ confirmed2: !checked });
  };

  nextButtonDisabled = (step: number) => {
    // eslint-disable-next-line max-len
    // const emailRegExp = /^[\w-]+(\.[\w-]+)*@([a-z0-9-]+(\.[a-z0-9-]+)*?\.[a-z]{2,6}|(\d{1,3}\.){3}\d{1,3})(:\d{4})?$/;
    const phoneRegExp = /^\d{8,12}$/;
    switch (step) {
      case -1:
        return false;
      case 0:
        if (this.state.givenName
            && this.state.email && this.state.phoneNumber) {
          if (!phoneRegExp.test(this.state.phoneNumber)) {
            return true;
          }
          for (let i = 0; i < Object.keys(this.state.sameInfoForBook).length; i += 1) {
            if (!this.state.sameInfoForBook[i]
              && (!(this.state.address1s[i])
                || !(this.state.receiverPhoneNumbers[i]) || !(this.state.receiverNames[i]))
            ) {
              return true;
            }
          }
          return false;
        }
        return true;
      case 1:
        if (this.state.payer && this.state.confirmed2) {
          return false;
        }
        return true;
      case 2:
        return false;
      default:
        return true;
    }
  };

  render() {
    const { classes } = this.props;

    return (
      <Container component="main" maxWidth="xl">
        <main className={classes.layout}>
          <Paper className={classes.paper}>
            <Typography component="h1" variant="h4" align="center">
              주문하기
            </Typography>
            <Stepper activeStep={this.state.activeStep} className={classes.stepper}>
              {steps.map((label) => (
                <Step key={label}>
                  <StepLabel>{label}</StepLabel>
                </Step>
              ))}
            </Stepper>
            <>
              {this.state.activeStep === steps.length ? (
                <>
                  <Typography variant="h6" gutterBottom>
                    주문해 주셔서 고맙습니다!
                  </Typography>
                  <Typography variant="subtitle1" color="secondary" gutterBottom>
                    다음 계좌로 입금 부탁드립니다. MyPage에서도 계좌 확인이 가능합니다.
                  </Typography>
                  <Typography variant="h6" color="primary" gutterBottom>
                    국민은행 618701-04-129813 오은지(도서출판 한티재)
                  </Typography>
                  <Typography variant="subtitle1">
                    <br />
                    문의: 053-743-8368
                    <br />
                    hantibooks@gmail.com
                  </Typography>
                  <Button
                    onClick={() => this.props.history.push('/mypage')}
                    className={classes.button}
                    color="secondary"
                    variant="outlined"
                  >
                    MyPage에서 주문 확인하기
                  </Button>
                </>
              ) : (
                <>
                  {this.getStepContent(this.state.activeStep)}
                  <div className={classes.buttons}>
                    {this.state.activeStep !== -1 && (
                      <Button onClick={this.handleBack} className={classes.button}>
                        이전
                      </Button>
                    )}
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={this.handleNext}
                      className={classes.button}
                      disabled={this.nextButtonDisabled(this.state.activeStep)}
                    >
                      {this.state.activeStep === steps.length - 1 ? '주문하기' : '다음'}
                    </Button>
                  </div>
                </>
              )}
            </>
          </Paper>
          <Copyright />
        </main>
      </Container>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getMeStatus: state.user.getMeStatus,
  me: state.user.me,
  basketStatus: state.user.basketStatus,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
  onGetBasket: () => dispatch(userActions.getBasket()),
  onGetBasket202006NewBook: () => dispatch(userActions.getBasket202006NewBook()),
  onOrderBasket: (basketId: number, familyName: string, givenName: string, email: string,
    phoneNumber: string, receiverFamilyName: string, receiverGivenName: string,
    address: string, postalCode: string, payer: string) => dispatch(userActions.orderBasket(
    basketId,
    familyName,
    givenName,
    email,
    phoneNumber,
    receiverFamilyName,
    receiverGivenName,
    address,
    postalCode,
    payer,
  )),
  onOrderBasket202006NewBook: (basketId: number, name: string, email: string,
    phoneNumber: string, addresses: any, receiverPhoneNumbers: any, receiverNames: any,
    signs: any, payer: string) => dispatch(userActions.orderBasket202006NewBook(
    basketId,
    name,
    email,
    phoneNumber,
    addresses,
    receiverPhoneNumbers,
    receiverNames,
    signs,
    payer,
  )),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Order));
