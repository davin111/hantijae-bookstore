import React, { Component } from 'react';

export interface Props {
  title: string;
  description: string;
}

class Book extends Component<Props, object> {
    render() {
      const { title, description } = this.props;
  
      return (
        <div className="book">
          <div className="title">
            제목: {title}
          </div>
          <div className="description">
            설명: {description}
          </div>
        </div>
      );
    }
}

export default Book;
