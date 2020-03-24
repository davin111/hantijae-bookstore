import React, { Component } from 'react';

interface Props {
  title: string;
  description: number;
}

// eslint-disable-next-line react/prefer-stateless-function
class Header extends Component<Props, object> {
  render() {
    const { title, description } = this.props;

    return (
      <div className="book">
        <div className="title">
          {title}
        </div>
        <div className="description">
          {description}
        </div>
      </div>
    );
  }
}

export default Header;
