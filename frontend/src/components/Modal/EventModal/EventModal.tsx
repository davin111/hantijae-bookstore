import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';

import { userStatus } from '../../../constants/constants';
import { stateActions } from '../../../store/actions';
import './EventModal.css';


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
  eventModal: boolean;
  onCloseEventModal: () => any;
  history: any;
  classes: any;
  me: any;
  getMeStatus: string;
}

interface State{
  open: boolean;
}

class EventModal extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      open: false,
    };
  }

  componentDidUpdate(prevProps: Props) {
    const date = new Date();
    if (prevProps.getMeStatus !== this.props.getMeStatus || prevProps.me !== this.props.me) {
      if (this.props.getMeStatus === userStatus.FAILURE) {
      // eslint-disable-next-line react/no-did-update-set-state
        this.setState({ open: true });
      }
    }
  }

  clickCancelHandler() {
    this.setState({ open: false });
  }

  render() {
    const { classes } = this.props;


    return (
      <Modal
        show={this.state.open}
        onHide={() => this.clickCancelHandler()}
      >
        <Modal.Header>
          <Typography className="EventNoti" component="h1" variant="h5" color="primary">
            한티재 10주년 기념 ‘10권 10만 원 책바구니’ 특판 이벤트
          </Typography>
        </Modal.Header>
        <Modal.Body>
          <Typography className="EventNoti" variant="body1">
            <div className="EventDescriptionModal">
              <li>
                책의 정가와 상관 없이 한티재 책 최대 10권을 10만 원에 구입하실 수 있습니다.
                단, 10권보다 적게 담거나, 정가 총액이 10만 원보다 적어도 결제 금액은 10만 원입니다.
              </li>
              <li>
                특판 이벤트에서 2020년 올해 나온 신간은 제외됩니다.
              </li>
              <li>
                한티재 온라인 책창고를 둘러보시고 책바구니에 책을 담아주세요. 지난 10년 동안 한티재는 총 108종의 단행본을 출간했습니다(절판 12종 포함).
              </li>
              <li>
                문의: hantibooks@gmail.com / 053-743-8368
              </li>
            </div>
          </Typography>
          <Button
            type="button"
            fullWidth
            variant="outlined"
            color="secondary"
            className={classes.submit}
            onClick={() => {
              this.clickCancelHandler();
              this.props.history.push('/hantijae');
            }}
          >
            도서출판 한티재에 대해 알아보기
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
            확인
          </Button>
        </Modal.Body>
      </Modal>
    );
  }
}

const mapStateToProps = (state: any) => ({
  eventModal: state.state.modal.eventModal,
  me: state.user.me,
  getMeStatus: state.user.getMeStatus,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseEventModal: () => dispatch(stateActions.closeEventModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(EventModal));
