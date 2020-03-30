import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../store/actions';

interface Props {
  onGetMe: () => any;
  me: any;
  getMeStatus: string;
  history: any;
}

class Auth extends Component<Props> {
  componentDidMount() {
    this.props.onGetMe();
  }

  render() {
    return (
      <div className="Auth" />
    );
  }
}

const mapStateToProps = (state: any) => ({
  getMeStatus: state.user.getMeStatus,
  me: state.user.me,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
});

export default connect(mapStateToProps, mapDispatchToProps)(Auth);
