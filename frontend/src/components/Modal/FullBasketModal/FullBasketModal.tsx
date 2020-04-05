import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';

import { userActions, stateActions } from '../../../store/actions';
import './FullBasketModal.css';


const styles = (theme: any) => createStyles({
  paper: {
    marginTop: theme.spacing(8),
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  avatar: {
    margin: theme.spacing(1),
    backgroundColor: theme.palette.secondary.main,
  },
  form: {
    width: '100%', // Fix IE 11 issue.
    marginTop: theme.spacing(1),
  },
  submit: {
    margin: theme.spacing(3, 0, 2),
  },
});

interface Props {
  fullBasketModal: boolean;
  onCloseFullBasketModal: () => any;
  history: any;
  classes: any;
}

class FullBasketModal extends Component<Props> {
  clickCancelHandler() {
    this.props.onCloseFullBasketModal();
  }

  render() {
    const { classes } = this.props;
    return (
      <Modal
        show={this.props.fullBasketModal}
        onHide={() => this.clickCancelHandler()}
      >
        <Modal.Header>
          <Typography className="FullBookBasket" component="h1" variant="h5">
            책바구니를 초과하는 수량입니다! 책바구니를 정리해주세요.
          </Typography>
        </Modal.Header>
        <Modal.Body>
          <Button
            type="button"
            fullWidth
            variant="contained"
            color="secondary"
            className={classes.submit}
            onClick={() => {
              this.clickCancelHandler();
              this.props.history.push('/order');
            }}
          >
            주문하러 가기
          </Button>
          <Button
            type="button"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
            onClick={() => {
              this.clickCancelHandler();
              this.props.history.push('/bookbasket');
            }}
          >
            책바구니 내역 확인하러 가기
          </Button>
        </Modal.Body>
      </Modal>
    );
  }
}

const mapStateToProps = (state: any) => ({
  fullBasketModal: state.state.modal.fullBasketModal,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseFullBasketModal: () => dispatch(stateActions.closeFullBasketModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(FullBasketModal));
