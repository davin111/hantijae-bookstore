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
          /* eslint-disable-next-line */
          src={require('./한티재 책창고.png')}
        />
      </div>
    );
  }
}

export default Title;
