import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';

// eslint-disable-next-line import/no-cycle
import { Login } from '../..';
import { stateActions } from '../../../store/actions';
import './LoginModal.css';


interface Props {
  loginModal: boolean;
  onCloseLoginModal: () => any;
  history: any;
}

class LoginModal extends Component<Props> {
  clickCancelHandler() {
    this.props.onCloseLoginModal();
  }

  render() {
    return (
      <Modal
        show={this.props.loginModal}
        onHide={() => this.clickCancelHandler()}
      >
        <Modal.Body>
          <Login history={this.props.history} withoutLogin={false} />
        </Modal.Body>
      </Modal>
    );
  }
}

const mapStateToProps = (state: any) => ({
  loginModal: state.state.modal.loginModal,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseLoginModal: () => dispatch(stateActions.closeLoginModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(LoginModal);
