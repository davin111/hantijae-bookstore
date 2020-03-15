import React, { Component } from 'react';

export interface Props {
  title: string;
  description: number;
}

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
