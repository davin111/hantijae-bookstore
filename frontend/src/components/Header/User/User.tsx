import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../../store/actions';
import './User.css';
import UserImg from './bookcart.png';

interface Props {
  onGetMe: () => any;
  me: any;
  getMeStatus: string;
}

class User extends Component<Props> {
  componentDidMount() {
    this.props.onGetMe();
  }

  clickBookIconHandler() {
    console.log(this.props.me);
  }

  render() {
    return (
      <div className="User">
        <h5>{}</h5>
        <div className="UserPictire">
          {/* eslint-disable-next-line */}
          <img src={UserImg} />
        </div>
        {/* eslint-disable-next-line */}
        <div className="Notification" onClick={() => {}}>1</div>

      </div>
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

export default connect(mapStateToProps, mapDispatchToProps)(User);
