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
import { createStyles, withStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';

import { userStatus } from '../../constants/constants';
import { userActions } from '../../store/actions';

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
    marginTop: theme.spacing(3),
  },
  submit: {
    margin: theme.spacing(3, 0, 2),
  },
});

interface Props {
  history: any;
  classes: any;
  signupStatus: string;
  user: any;
  onSignup: (username: string, email: string, password: string,
    familyName: string, givenName: string, notifiable: boolean) => any;
}

interface State {
  username: string;
  email: string;
  password: string;
  familyName: string;
  givenName: string;
  notifiable: boolean;
  idValidated: boolean;
  passwordValidated: boolean;
  emailValidated: boolean;
}

class SignupPage extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      username: '',
      email: '',
      password: '',
      familyName: '',
      givenName: '',
      notifiable: false,
      idValidated: true,
      passwordValidated: true,
      emailValidated: true,
    };
  }

  componentDidMount() {
    window.scrollTo(0, 0);
  }

  clickSignupHandler() {
    const idRegExp = /^[a-z0-9]{5,20}$/;
    const passwordRegExp = /(?=.*\d{1,50})(?=.*[~`!@#$%^&*()-+=]{1,50})(?=.*[a-zA-Z]{2,50}).{8,50}$/;
    const emailRegExp = /^[\w-]+(\.[\w-]+)*@([a-z0-9-]+(\.[a-z0-9-]+)*?\.[a-z]{2,6}|(\d{1,3}\.){3}\d{1,3})(:\d{4})?$/;
    if (idRegExp.test(this.state.username)) {
      this.setState({ idValidated: true });
    } else {
      this.setState({ idValidated: false });
    }
    if (passwordRegExp.test(this.state.password)) {
      this.setState({ passwordValidated: true });
    } else {
      this.setState({ passwordValidated: false });
    }
    if (emailRegExp.test(this.state.email)) {
      this.setState({ emailValidated: true });
    } else {
      this.setState({ emailValidated: false });
    }

    if (idRegExp.test(this.state.username) && passwordRegExp.test(this.state.password)
      && emailRegExp.test(this.state.email)) {
      this.props.onSignup(this.state.username, this.state.email, this.state.password,
        this.state.familyName, this.state.givenName, this.state.notifiable)
        .then(() => {
          if (this.props.signupStatus === userStatus.SUCCESS) {
            this.props.history.push('/');
          } else if (this.props.signupStatus === userStatus.FAILURE_USERNAME) {
            console.log('중복된 username입니다!');
          } else {
            console.log('ERROR!');
          }
        });
    }
  }

  render() {
    const { classes } = this.props;
    let warning = null;
    if (this.props.signupStatus === userStatus.FAILURE_USERNAME) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          이미 존재하는 아이디입니다.
        </Typography>
      );
    }
    if (!this.state.passwordValidated) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          잘못된 비밀번호 형식입니다.
        </Typography>
      );
    }
    if (!this.state.emailValidated) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          잘못된 이메일 형식입니다.
        </Typography>
      );
    }
    if (!this.state.idValidated) {
      warning = (
        <Typography variant="h6" color="secondary" align="center">
          잘못된 아이디 형식입니다.
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
            회원 가입
          </Typography>
          <form className={classes.form} noValidate>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={12}>
                <TextField
                  autoComplete="fname"
                  name="firstName"
                  variant="outlined"
                  required
                  fullWidth
                  id="firstName"
                  label="이름"
                  autoFocus
                  onChange={(e) => this.setState({ givenName: e.target.value })}
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  variant="outlined"
                  required
                  fullWidth
                  id="username"
                  label="아이디"
                  name="username"
                  autoComplete="off"
                  helperText="5글자에서 20글자 사이의 숫자와 영어 소문자로 만들어주세요."
                  onChange={(e) => this.setState({ username: e.target.value })}
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  variant="outlined"
                  required
                  fullWidth
                  id="email"
                  label="이메일"
                  name="email"
                  autoComplete="email"
                  helperText="실제 사용하는 이메일을 입력해주세요."
                  onChange={(e) => this.setState({ email: e.target.value })}
                />
              </Grid>
              <Grid item xs={12}>
                <TextField
                  variant="outlined"
                  required
                  fullWidth
                  name="password"
                  label="비밀번호"
                  type="password"
                  id="password"
                  autoComplete="current-password"
                  helperText="숫자와 특수문자를 각 1회 이상 사용해 8글자 이상으로 만들어주세요."
                  onChange={(e) => this.setState({ password: e.target.value })}
                />
              </Grid>
              <Grid item xs={12}>
                <FormControlLabel
                  control={(
                    <Checkbox
                      value="allowExtraEmails"
                      color="primary"
                      checked={this.state.notifiable}
                      onChange={() => {
                        const checked = this.state.notifiable;
                        this.setState({ notifiable: !checked });
                      }}
                    />
)}
                  label="한티재의 소식을 이메일을 통해 받겠습니다."
                />
              </Grid>
            </Grid>
            {warning}
            <Button
              type="button"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.submit}
              disabled={
                Boolean(!(this.state.givenName && this.state.username
                && this.state.email && this.state.password))
              }
              onClick={() => this.clickSignupHandler()}
            >
              회원 가입
            </Button>
            <Grid container justify="flex-end">
              <Grid item>
                <Link href="/login" variant="body2">
                  이미 가입하셨나요? 로그인하러 가기
                </Link>
              </Grid>
            </Grid>
          </form>
        </div>
        <Box mt={5}>
          <Copyright />
        </Box>
      </Container>
    );
  }
}

const mapStateToProps = (state: any) => ({
  signupStatus: state.user.signupStatus,
  user: state.user.login,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onSignup: (username: string, email: string, password: string,
    familyName: string, givenName: string, notifiable: boolean) => dispatch(
    userActions.signup(username, email, password, familyName, givenName, notifiable),
  ),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(SignupPage));
