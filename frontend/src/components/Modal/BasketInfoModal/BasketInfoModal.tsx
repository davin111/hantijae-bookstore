import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';

import { stateActions } from '../../../store/actions';
import './BasketInfoModal.css';


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
  basketInfoModal: boolean;
  onCloseBasketInfoModal: () => any;
  history: any;
  classes: any;
}

class BasketInfoModal extends Component<Props> {
  clickCancelHandler() {
    this.props.onCloseBasketInfoModal();
  }

  render() {
    const { classes } = this.props;
    return (
      <Modal
        show={this.props.basketInfoModal}
        onHide={() => this.clickCancelHandler()}
      >
        <Modal.Header>
          <Typography className="PostedBookInBasket" component="h1" variant="h5">
            책바구니에 책을 담았습니다.
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
            지금까지 담은 책바구니 주문하러 가기
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
          <Button
            type="button"
            fullWidth
            variant="contained"
            color="default"
            className={classes.submit}
            onClick={() => {
              this.clickCancelHandler();
            }}
          >
            책 더 둘러보기
          </Button>
        </Modal.Body>
      </Modal>
    );
  }
}

const mapStateToProps = (state: any) => ({
  basketInfoModal: state.state.modal.basketInfoModal,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseBasketInfoModal: () => dispatch(stateActions.closeBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(BasketInfoModal));
