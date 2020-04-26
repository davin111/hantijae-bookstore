import React, { Component, Dispatch } from 'react';
import { Modal } from 'react-bootstrap';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import Typography from '@material-ui/core/Typography';
import { withStyles, createStyles } from '@material-ui/core/styles';
import ReactPlayer from 'react-player';

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
            전태일 50주기 공동 출판 프로젝트 ─ 너는 나다
          </Typography>
        </Modal.Header>
        <Modal.Body>
          <div className="NewBookStandModal">
            {/* eslint-disable-next-line */}
          <img src={require('../../../containers/HantijaePage/new_book.png')} />
          </div>
          <ReactPlayer
            className="ModalYouTube"
            url="https://www.youtube.com/watch?v=bW3SAa9jL9Q"
            controls
          />
          <Typography className="EventNoti" variant="body1">
            <Button
              type="button"
              onClick={() => this.props.history.push('/book=109')}
              variant="contained"
              color="primary"
              size="medium"
            >
              바로가기
            </Button>
            <p className="EventDescriptionModal">
              <h3>
                “우리 생애의 노동은 인간다운가”
              </h3>
              <p>
                일, 밥, 집, 시간, 공부 …
                누구도 자유로울 수 없는 삶의 문제들을 키워드로,
                전태일의 생애와 오늘 여기 청년들의 현실을 씨실과 날실로 엮었다.
                사람과 세상을 대하는 전혀 다른 시야를 열어 준 전태일과 함께
                한국 사회 ‘그늘의 지도’ 곳곳을 찾아나서는 길 위의 인문학.
                우리 일상을 지배하는 생각과 말들의 규칙에 맞서
                행복과 사랑의 공공성을 되찾으려는, 아프지만 유쾌한 여정.
              </p>
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
