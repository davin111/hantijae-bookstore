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
        <img
          className="BookStoreTitleImage"
          onClick={() => this.props.history.push('/')}
          src={"https://hantijae-assets.s3.ap-northeast-2.amazonaws.com/misc/hantijae-bookstore-title.png"}
        />
      </div>
    );
  }
}

export default Title;
