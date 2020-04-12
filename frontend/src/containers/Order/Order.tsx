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
  onGetBasket: () => any;
  onOrderBasket: (basketId: number, familyName: string, givenName: string, email: string,
    phoneNumber: string, receiverFamilyName: string, receiverGivenName: string,
    address: string, postalCode: string, payer: string) => any;
}

interface State {
  activeStep: number;
  familyName: string;
  givenName: string;
  email: string;
  phoneNumber: string;
  sameReceiver: boolean;
  receiverFamilyName: string;
  receiverGivenName: string;
  address1: string;
  address2: string;
  postalCode: string;
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
      receiverFamilyName: '',
      receiverGivenName: '',
      address1: '',
      address2: '',
      postalCode: '',
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
    this.props.onGetBasket()
      .then(() => {
        if (this.props.basket.books.length === 0) {
          this.props.history.push('/');
        }
      });
  }

  handleNext = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const step = this.state.activeStep;
    if (step === 2) {
      let receiverFamilyName = this.state.familyName;
      let receiverGivenName = this.state.givenName;
      if (!this.state.sameReceiver) {
        receiverFamilyName = this.state.receiverFamilyName;
        receiverGivenName = this.state.receiverGivenName;
      }

      let address = this.state.address1;
      if (this.state.address2 !== '') {
        address = [this.state.address1, this.state.address2].join(', ');
      }

      this.props.onOrderBasket(
        this.props.basket.id,
        this.state.familyName,
        this.state.givenName,
        this.state.email,
        this.state.phoneNumber,
        receiverFamilyName,
        receiverGivenName,
        address,
        this.state.postalCode,
        this.state.payer,
      ).then(() => {
        if (this.props.basketStatus === basketStatus.SUCCESS) {
          this.setState({ activeStep: step + 1 });
          this.props.onGetBasket();
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
            address2={this.state.address2}
            postalCode={this.state.postalCode}
            changeFamilyName={this.changeFamilyName}
            changeGivenName={this.changeGivenName}
            changeEmail={this.changeEmail}
            changePhoneNumber={this.changePhoneNumber}
            sameReceiver={this.state.sameReceiver}
            changeSameReceiver={this.changeSameReceiver}
            changeReceiverFamilyName={this.changeReceiverFamilyName}
            changeReceiverGivenName={this.changeReceiverGivenName}
            changeAddress1={this.changeAddress1}
            changeAddress2={this.changeAddress2}
            changePostalCode={this.changePostalCode}
            confirmed={this.state.confirmed}
            changeConfirmed={this.changeConfirmed}
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

  changeReceiverFamilyName = (e: any) => {
    this.setState({ receiverFamilyName: e.target.value });
  };

  changeReceiverGivenName = (e: any) => {
    this.setState({ receiverGivenName: e.target.value });
  };

  changeAddress1 = (e: any) => {
    this.setState({ address1: e.target.value });
  };

  changeAddress2 = (e: any) => {
    this.setState({ address2: e.target.value });
  };

  changePostalCode = (e: any) => {
    this.setState({ postalCode: e.target.value });
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
    const emailRegExp = /^[\w-]+(\.[\w-]+)*@([a-z0-9-]+(\.[a-z0-9-]+)*?\.[a-z]{2,6}|(\d{1,3}\.){3}\d{1,3})(:\d{4})?$/;
    const phoneRegExp = /^\d{8,12}$/;
    switch (step) {
      case -1:
        return false;
      case 0:
        if (this.state.givenName && this.state.confirmed
            && this.state.email && this.state.phoneNumber
            && this.state.address1) {
          if (!this.state.sameReceiver
              && !(this.state.receiverGivenName)) {
            return true;
          }
          if (!emailRegExp.test(this.state.email) || !phoneRegExp.test(this.state.phoneNumber)) {
            return true;
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
                    한티재 10주년 기념 특판 이벤트에 참여해 주셔서 고맙습니다!
                  </Typography>
                  <Typography variant="subtitle1">
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
                    MyPage에서 확인하기
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
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Order));
