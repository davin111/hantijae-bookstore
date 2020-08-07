import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';
// import ReactPlayer from 'react-player';

import { stateActions, userActions } from '../../../store/actions';
import { basketStatus, userStatus } from '../../../constants/constants';
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
  onOpenLoginModal: () => any;
  onOpenFullBasketModal: () => any;
  onOpenBasketInfoModal: () => any;
  history: any;
  classes: any;
  me: any;
  getMeStatus: string;
  basketStatus: string;
  onPostBookInBasket202006NewBook: (id: number, count: number) => any;
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
    if (prevProps.getMeStatus !== this.props.getMeStatus || prevProps.me !== this.props.me) {
      // if (this.props.getMeStatus === userStatus.FAILURE) {
      // eslint-disable-next-line react/no-did-update-set-state
      this.setState({ open: true });
      // }
    }
  }

  clickPostBookHandler = () => {
    if (this.props.getMeStatus === userStatus.FAILURE || this.props.me.anonymous === true) {
      this.props.onOpenLoginModal();
    } else {
      this.props.onPostBookInBasket202006NewBook(110, 1)
        .then(() => {
          if (this.props.basketStatus === basketStatus.SUCCESS) {
            this.props.onOpenBasketInfoModal();
          }
          if (this.props.basketStatus === basketStatus.FAILURE_MAX_BOOK) {
            this.props.onOpenFullBasketModal();
          }
        });
    }
  };

  clickCancelHandler() {
    this.setState({ open: false });
    this.props.onCloseEventModal();
  }

  render() {
    const { classes } = this.props;


    return (
      <Modal
        show={this.state.open || this.props.eventModal}
        onHide={() => this.clickCancelHandler()}
      >
        <Modal.Header>
          <h3 className="NewBookTitleModal">
            『성서, 퀴어를 옹호하다』 텀블벅 펀딩 진행중!
          </h3>
          <Typography className="EventNoti" component="h1" variant="h5" color="primary">
            왜 개신교는 그렇게 성소수자를 부정할까?
            <br />
            정말로 성서는 동성애를 금지하고 있을까?
          </Typography>
        </Modal.Header>
        <Modal.Body>
          <p className="EventDescriptionModal">
            일정 금액 이상 후원 시 금속 뱃지와 스티커를 증정합니다.
          </p>
          <hr className="CenterLineModal" />
          <h3 className="NewBookTitles">
            『성서, 퀴어를 옹호하다』
            <br />
            ― 성서학자가 들려주는 기독교와 성소수자 이야기
          </h3>
          <div className="NewBookStandModal">
            {/* eslint-disable-next-line */}
          <img src={require('../../../containers/BookDetail/book_covers_3d/성서, 퀴어를 옹호하다.jpeg')} />
          </div>
          <Typography className="EventNoti" variant="body1">
            <Button
              type="button"
              onClick={() => window.open('https://tumblbug.com/queerinbible')}
              variant="contained"
              color="primary"
              size="medium"
              style={{
                backgroundColor: '#7EC7C5',
              }}
            >
              프로젝트 밀어주기
            </Button>
            {/* <Button
              type="button"
              onClick={() => this.clickPostBookHandler()}
              variant="contained"
              color="secondary"
              size="medium"
            >
              책바구니에 담기
            </Button> */}
            <p className="EventDescriptionModal">
              ♥ 펀딩 기간 : 2020년 7월 17일(금) ~ 8월 20일(목)
              <br />
              ♥ 예상 선물 수령일 : 9월 15일(화)
              <br />
              &nbsp;&nbsp;8월 20일 - 펀딩 마감
              <br />
              &nbsp;&nbsp;9월 7일 - 모금액 정산 완료, 제작비 결제
              <br />
              &nbsp;&nbsp;9월 15일 - 예상 선물 수령일
              <br />
              ♥ 문의 : 053-743-8368 | hantibooks@gmail.com
            </p>
          </Typography>
          {/* <Button
            type="button"
            fullWidth
            variant="outlined"
            color="secondary"
            className={classes.submit}
            onClick={() => {
              this.clickCancelHandler();
              this.props.history.push('/book=109');
            }}
          >
            바로가기
          </Button> */}
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
  basketStatus: state.user.basketStatus,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseEventModal: () => dispatch(stateActions.closeEventModal()),
  onPostBookInBasket202006NewBook: (id: number, count: number) => dispatch(
    userActions.postBookInBasket202006NewBook(id, count),
  ),
  onOpenLoginModal: () => dispatch(stateActions.openLoginModal()),
  onOpenFullBasketModal: () => dispatch(stateActions.openFullBasketModal()),
  onOpenBasketInfoModal: () => dispatch(stateActions.openBasketInfoModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(EventModal));
