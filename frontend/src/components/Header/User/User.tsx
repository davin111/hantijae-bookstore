import React, { Component } from 'react';
import './User.css';
import UserImg from './kiki.jpeg';

class User extends Component {
  render() {
    return (
      <div className="User">
        <div className="UserPictire">
          <img src={UserImg} />
        </div>
        <div className="Notification" onClick={() => {}}>1</div>
      </div>
    );
  }
}

export default User;
