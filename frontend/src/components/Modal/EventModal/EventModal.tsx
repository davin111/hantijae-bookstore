import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';
// import ReactPlayer from 'react-player';

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
    if (prevProps.getMeStatus !== this.props.getMeStatus || prevProps.me !== this.props.me) {
      // if (this.props.getMeStatus === userStatus.FAILURE) {
      // eslint-disable-next-line react/no-did-update-set-state
      this.setState({ open: true });
      // }
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
          <h3 className="NewBookTitleModal">
            한티재 신간
          </h3>
          <Typography className="EventNoti" component="h1" variant="h5" color="primary">
            “사랑과 위로를 나에게 선물하세요”
            <br />
            ― 『당신이 나의 백신입니다』 저자 자필 사인본 이벤트
          </Typography>
        </Modal.Header>
        <Modal.Body>
          <p className="EventDescriptionModal">
            따뜻한 의사 김동은 선생님의 첫 책 출간을 기념하여
            <br />
            저자 자필 사인본 이벤트를 준비했습니다.
            <br />
            한티재 온라인 책창고에서 책을 주문하시면,
            <br />
            힘들고 아픈 사람 곁에 늘 함께 있는 선생님의
            <br />
            따뜻한 글씨를 책에 담아 보내드립니다.
            <br />
            많은 신청 부탁드립니다!
          </p>
          <hr className="CenterLineModal" />
          <h3 className="NewBookTitles">
            『당신이 나의 백신입니다』
            <br />
            ― 감염병과 혐오의 시대, 의사 김동은이 만난 아름다운 사람들
          </h3>
          <h3 className="NewBookInfos">
            김동은 지음
            <br />
            (2020년 6월 22일 출간 | 15,000원)
          </h3>
          <div className="NewBookStandModal">
            {/* eslint-disable-next-line */}
          <img src={require('../../../containers/BookDetail/book_covers_3d/당신이 나의 백신입니다.png')} />
          </div>
          <Typography className="EventNoti" variant="body1">
            <Button
              type="button"
              onClick={() => this.props.history.push('/book=110')}
              variant="contained"
              color="primary"
              size="medium"
            >
              바로가기
            </Button>
            <p className="EventDescriptionModal">
              ♥ 이벤트 기간 : 2020년 6월 8일(월) ~ 6월 20일(토)
              <br />
              ♥ 책 발송일 : 6월 22일(월)
              <br />
              ♥ 이벤트 참가 방법
              <br />
              &nbsp;&nbsp;1. 한티재 온라인 책창고에서 회원 가입을 합니다.
              <br />
              &nbsp;&nbsp;2. 『당신이 나의 백신입니다』를 주문합니다.
              <br />
              &nbsp;&nbsp;3. 주문 단계에서, 사인 받을 분의 이름을 확인하여 정확히 입력해주세요.
              <br />
              &nbsp;&nbsp;4. ‘주문 완료’ 버튼을 누르고 결제해주세요. 결제가 확인되어야 발송됩니다.
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
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onCloseEventModal: () => dispatch(stateActions.closeEventModal()),
});

export default connect(mapStateToProps, mapDispatchToProps)(withStyles(styles)(EventModal));
