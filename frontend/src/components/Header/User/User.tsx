import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../../store/actions';
import './User.css';
import BookBasketImg from './bookbasket.png';
import { userStatus } from '../../../constants/constants';

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
    bookCount = Number.isInteger(this.props.basket.bookCount) ? this.props.basket.bookCount : 0;
    if (this.props.getMeStatus === userStatus.FAILURE) {
      username = '비로그인 유저';
      logButton = <button className="LogButton" type="button" onClick={() => this.props.history.push('/login')}>로그인</button>;
    } else if (this.props.me.anonymous === true) {
      username = '비로그인 유저';
      logButton = <button className="LogButton" type="button" onClick={() => this.props.history.push('/login')}>로그인</button>;
    } else {
      username = this.props.me.username;
      logButton = <button className="LogButton" type="button" onClick={() => this.clickLogoutHandler()}>로그아웃</button>;
    }

    return (
      <div className="User">
        <h5>
          {username}
          {' '}
          님
        </h5>
        <div className="UserPictire">
          {/* eslint-disable-next-line */}
          <img src={BookBasketImg} onClick={() => this.props.history.push('/bookbasket')}/>
        </div>
        {/* eslint-disable-next-line */}
    <div className="Notification" onClick={() => this.props.history.push('/bookbasket')}>{bookCount}</div>
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
