import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../store/actions';
import { Login } from '../../components';
import './LoginPage.css';

interface Props {
  history: any;
}

interface State {
  username: string;
  password: string;
}

class LoginPage extends Component<Props> {
  render() {
    return (
      <Login history={this.props.history} />
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

export default connect(mapStateToProps, mapDispatchToProps)(LoginPage);
