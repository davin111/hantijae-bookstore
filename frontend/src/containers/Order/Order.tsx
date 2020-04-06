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

import { userStatus } from '../../constants/constants';
import { userActions } from '../../store/actions';
import AddressForm from './AddressForm/AddressForm';
import PaymentForm from './PaymentForm/PaymentForm';
import Review from './Review/Review';

function Copyright() {
  return (
    <Typography variant="body2" color="textSecondary" align="center">
      {'Copyright © '}
      <Link color="inherit" href="http://hantijae-bookstore.com/">
        도서출판 한티재
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
    marginLeft: theme.spacing(2),
    marginRight: theme.spacing(2),
    [theme.breakpoints.up(600 + theme.spacing(2) * 2)]: {
      width: 600,
      marginLeft: 'auto',
      marginRight: 'auto',
    },
  },
  paper: {
    marginTop: theme.spacing(3),
    marginBottom: theme.spacing(3),
    padding: theme.spacing(2),
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
  baksetStatus: string;
  basket: any;
  onGetBasket: () => any;
}

interface State {
  activeStep: number;
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

const steps = ['주문 정보 입력', '계좌 입금 정보', '책바구니 내역 확인'];

class Order extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      activeStep: 0,
      familyName: '',
      givenName: '',
      email: '',
      phoneNumber: '',
      receiverFamilyName: '',
      receiverGivenName: '',
      address1: '',
      address2: '',
      postalCode: '',
      payer: '',
    };
  }

  componentDidMount() {
    this.props.onGetBasket();
  }

  handleNext = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const step = this.state.activeStep;
    this.setState({ activeStep: step + 1 });
  };

  handleBack = () => {
    // eslint-disable-next-line react/no-access-state-in-setstate
    const step = this.state.activeStep;
    this.setState({ activeStep: step - 1 });
  };

  getStepContent = (step: number) => {
    switch (step) {
      case 0:
        return (
          <AddressForm
            changeFamilyName={this.changeFamilyName}
            changeGivenName={this.changeGivenName}
            changeEmail={this.changeEmail}
            changePhoneNumber={this.changePhoneNumber}
            changeReceiverFamilyName={this.changeReceiverFamilyName}
            changeReceiverGivenName={this.changeReceiverGivenName}
            changeAddress1={this.changeAddress1}
            changeAddress2={this.changeAddress2}
            changePostalCode={this.changePostalCode}
          />
        );
      case 1:
        return <PaymentForm changePayer={this.changePayer} />;
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

  changePayer = (e: any) => {
    this.setState({ payer: e.target.value });
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
                  <Typography variant="h5" gutterBottom>
                    Thank you for your order.
                  </Typography>
                  <Typography variant="subtitle1">
                    Your order number is #2001539. We have emailed your order confirmation, and will
                    send you an update when your order has shipped.
                  </Typography>
                </>
              ) : (
                <>
                  {this.getStepContent(this.state.activeStep)}
                  <div className={classes.buttons}>
                    {this.state.activeStep !== 0 && (
                      <Button onClick={this.handleBack} className={classes.button}>
                        이전
                      </Button>
                    )}
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={this.handleNext}
                      className={classes.button}
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
  basketStatus: state.user.basketStatus,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetBasket: () => dispatch(userActions.getBasket()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Order));
