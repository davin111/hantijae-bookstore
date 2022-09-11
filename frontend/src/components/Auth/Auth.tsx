import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';

import { userActions } from '../../store/actions';

interface Props {
  onGetMe: () => any;
  me: any;
  getMeStatus: string;
  history: any;
}

interface State {
  location: string;
}

class Auth extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      location: '',
    };
  }

  componentDidMount() {
    this.props.onGetMe();
    this.setState({ location: this.props.history.location.pathname });
  }

  shouldComponentUpdate() {
    return true;
  }

  componentDidUpdate(prevProps: Props, prevState: State) {
    if (this.props.history.location.pathname !== this.state.location) {
      this.props.onGetMe().then(() => {
        this.setState({ location: this.props.history.location.pathname });
      });
    }
  }

  render() {
    return (
      <div className="Auth" />
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

export default connect(mapStateToProps, mapDispatchToProps)(Auth);
