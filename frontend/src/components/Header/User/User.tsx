import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import PermIdentityIcon from '@material-ui/icons/PermIdentity';

import { userActions } from '../../../store/actions';
import { userStatus } from '../../../constants/constants';
import './User.css';
import BookBasketImg from './bookbasket.png';

interface Props {
  onGetMe: () => any;
  me: any;
  history: any;
  getMeStatus: string;
  basket: any;
  onLogout: () => any;
}

class User extends Component<Props> {
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
      username = '비회원';
      logButton = (
        <Button
          type="button"
          onClick={() => this.props.history.push('/login')}
          variant="contained"
          color="primary"
          size="small"
        >
          로그인
        </Button>
      );
    } else if (this.props.me.anonymous === true) {
      username = '비회원';
      logButton = (
        <Button
          type="button"
          onClick={() => this.props.history.push('/login')}
          variant="contained"
          color="primary"
          size="small"
        >
          로그인
        </Button>
      );
    } else {
      username = this.props.me.username;
      logButton = (
        <Button
          type="button"
          onClick={() => this.clickLogoutHandler()}
          variant="contained"
          color="default"
          size="small"
        >
          로그아웃
        </Button>
      );
    }

    return (
      <div className="User">
        <Button
          type="button"
          variant="contained"
          color="default"
          size="small"
          onClick={() => this.props.history.push('/mypage')}
          endIcon={<PermIdentityIcon />}
        >
          {username}
        </Button>
        <div className="UserPictire">
          {/* eslint-disable-next-line */}
          <img src={BookBasketImg} onClick={() => this.props.history.push('/bookbasket')}/>
        </div>
        {/* eslint-disable-next-line */}
      <div className="BasketCount" onClick={() => this.props.history.push('/bookbasket')}>{bookCount}</div>
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
