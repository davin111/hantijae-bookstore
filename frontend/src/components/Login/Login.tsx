import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Avatar from '@material-ui/core/Avatar';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import TextField from '@material-ui/core/TextField';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Checkbox from '@material-ui/core/Checkbox';
import Link from '@material-ui/core/Link';
import Grid from '@material-ui/core/Grid';
import Box from '@material-ui/core/Box';
import LockOutlinedIcon from '@material-ui/icons/LockOutlined';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';

import { userStatus } from '../../constants/constants';
import { userActions, stateActions } from '../../store/actions';
import './Login.css';

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
  paper: {
    marginTop: theme.spacing(8),
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  avatar: {
    margin: theme.spacing(1),
    backgroundColor: theme.palette.secondary.main,
  },
  form: {
    width: '100%', // Fix IE 11 issue.
    marginTop: theme.spacing(1),
  },
  submit: {
    margin: theme.spacing(3, 0, 2),
  },
});

interface Props {
  history: any;
  classes: any;
  loginStatus: string;
  user: any;
  onLogin: (username: string, password: string) => any;
  onGetMe: () => any;
  withoutLogin: boolean;
  onCloseLoginModal: () => any;
  onDontSuggestLogin: () => any;
}

interface State {
  username: string;
  password: string;
}

class Login extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      username: '',
      password: '',
    };
  }

  clickLoginHandler() {
    this.props.onLogin(this.state.username, this.state.password)
      .then(() => {
        if (this.props.loginStatus === userStatus.SUCCESS) {
          if (this.props.history.location.pathname === '/login') {
            this.props.history.push('/');
          }
          this.props.onCloseLoginModal();
          this.props.onGetMe();
        }
      });
  }

  clickWithoutLoginHandler() {
    this.props.onCloseLoginModal();
    this.props.onDontSuggestLogin();
  }

  render() {
    const { classes } = this.props;
    let withoutLoginButton = null;
    if (this.props.withoutLogin) {
      withoutLoginButton = (
        <Button
          type="button"
          fullWidth
          variant="contained"
          color="default"
          className={classes.submit}
          onClick={() => this.clickWithoutLoginHandler()}
        >
          로그인 없이 이용 (책바구니 내역을 잃을 수 있습니다)
        </Button>
      );
    }

    let warning = null;
    if (this.props.loginStatus === userStatus.FAILURE_USERNAME) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          존재하지 않는 아이디입니다.
        </Typography>
      );
    } else if (this.props.loginStatus === userStatus.FAILURE) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          잘못된 비밀번호입니다.
        </Typography>
      );
    }

    return (
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Avatar className={classes.avatar}>
            <LockOutlinedIcon />
          </Avatar>
          <Typography component="h1" variant="h5">
            로그인
          </Typography>
          <form className={classes.form} noValidate>
            <TextField
              variant="outlined"
              margin="normal"
              required
              fullWidth
              id="username"
              label="아이디"
              name="username"
              autoComplete="off"
              autoFocus
              onChange={(e) => this.setState({ username: e.target.value })}
            />
            <TextField
              variant="outlined"
              margin="normal"
              required
              fullWidth
              name="password"
              label="비밀번호"
              type="password"
              id="password"
              autoComplete="current-password"
              onChange={(e) => this.setState({ password: e.target.value })}
            />
            <FormControlLabel
              control={<Checkbox value="remember" color="primary" />}
              label="다음에 자동 로그인"
            />
            {warning}
            <Button
              type="button"
              fullWidth
              variant="contained"
              color="secondary"
              className={classes.submit}
              onClick={() => this.clickLoginHandler()}
              disabled={
                Boolean(!(this.state.username && this.state.password))
              }
            >
              로그인
            </Button>
            <Button
              type="button"
              fullWidth
              variant="contained"
              color="primary"
              className="GoToSignupButton"
              onClick={() => this.props.history.push('/signup')}
            >
              회원 가입하러 가기
            </Button>
            {withoutLoginButton}
            <div className="GapMaker" />
            <Grid container>
              <Grid item xs>
                {/* eslint-disable-next-line jsx-a11y/anchor-is-valid */}
                <Link variant="body2">
                  비밀번호를 잊으셨나요? (현재 지원하지 않습니다)
                </Link>
              </Grid>
            </Grid>
          </form>
        </div>
        <Box mt={8}>
          <Copyright />
        </Box>
      </Container>
    );
  }
}

const mapStateToProps = (state: any) => ({
  loginStatus: state.user.loginStatus,
  user: state.user.login,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onLogin: (username: string, password: string) => dispatch(userActions.login(username, password)),
  onGetMe: () => dispatch(userActions.getMe()),
  onCloseLoginModal: () => dispatch(stateActions.closeLoginModal()),
  onDontSuggestLogin: () => dispatch(stateActions.dontSuggestLogin()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(Login));
