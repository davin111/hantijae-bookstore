import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../../store/actions';
import './User.css';
import UserImg from './bookcart.png';

interface Props {
  onGetMe: () => any;
  me: any;
  history: any;
  getMeStatus: string;
  basket: any;
  onLogout: () => any;
}

class User extends Component<Props> {
  clickBookIconHandler() {
    console.log(this.props.me);
  }

  clickLogoutHandler() {
    this.props.onLogout()
      .then(() => {
        this.props.onGetMe();
      });
  }

  render() {
    let username = '';
    let bookCount = 0;
    let logButton = null;
    if (Object.keys(this.props.me).length === 0) {
      username = '비로그인 유저';
      logButton = <button type="button" onClick={() => this.props.history.push('/login')}>로그인</button>;
    } else {
      bookCount = Number.isInteger(this.props.basket.bookCount) ? this.props.basket.bookCount : 0;
      if (this.props.me.anonymous === true) {
        username = '비로그인 유저';
        logButton = <button type="button" onClick={() => this.props.history.push('/login')}>로그인</button>;
      } else {
        username = this.props.me.username;
        logButton = <button type="button" onClick={() => this.clickLogoutHandler()}>로그아웃</button>;
      }
    }

    return (
      <div className="User">
        <h5>{username}</h5>
        <div className="UserPictire">
          {/* eslint-disable-next-line */}
          <img src={UserImg} />
        </div>
        {/* eslint-disable-next-line */}
    <div className="Notification" onClick={() => {}}>{bookCount}</div>
        {logButton}
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getMeStatus: state.user.getMeStatus,
  me: state.user.me,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
  onLogout: () => dispatch(userActions.logout()),
});

export default connect(mapStateToProps, mapDispatchToProps)(User);
