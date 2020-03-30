import React, { Component } from 'react';
import './User.css';
import UserImg from './kiki.jpeg';

class User extends Component {
  render() {
    return (
      <div className="User">
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

export default User;
