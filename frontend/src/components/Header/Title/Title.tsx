import React, { Component } from 'react';
import './Title.css';

interface Props {
  history: any;
}

// eslint-disable-next-line react/prefer-stateless-function
class Title extends Component<Props> {
  render() {
    return (
      <div className="Title">
        {/* eslint-disable-next-line */}
        <div onClick={() => this.props.history.push('/')}>한티재 온라인 책창고</div>
      </div>
    );
  }
}

export default Title;
