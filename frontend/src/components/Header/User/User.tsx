import React, { Component, Dispatch } from 'react';
import { connect } from 'react-redux';
import Button from '@material-ui/core/Button';
import PermIdentityIcon from '@material-ui/icons/PermIdentity';
import ShoppingBasketIcon from '@material-ui/icons/ShoppingBasket';

import { userActions } from '../../../store/actions';
import { userStatus } from '../../../constants/constants';
import './User.css';
// import BookBasketImg from './bookbasket.png';

interface Props {
  onGetMe: () => any;
  me: any;
  history: any;
  getMeStatus: string;
  basket: any;
  onLogout: () => any;
}

class User extends Component<Props> {
  clickLogoutHandler() {
    this.props.onLogout()
      .then(() => {
        this.props.onGetMe();
      });
  }

  render() {
    let username = '';
    let bookCount = 0;
    let logButton = null;
    bookCount = Number.isInteger(this.props.basket.bookCount) ? this.props.basket.bookCount : 0;
    if (this.props.getMeStatus === userStatus.FAILURE) {
      username = '비회원';
      logButton = (
        <Button
          type="button"
          onClick={() => this.props.history.push('/login')}
          variant="contained"
          color="primary"
          size="small"
        >
          로그인
        </Button>
      );
    } else if (this.props.me.anonymous === true) {
      username = '비회원';
      logButton = (
        <Button
          type="button"
          onClick={() => this.props.history.push('/login')}
          variant="contained"
          color="secondary"
          size="small"
        >
          로그인
        </Button>
      );
    } else {
      username = this.props.me.username;
      logButton = (
        <Button
          type="button"
          onClick={() => this.clickLogoutHandler()}
          variant="contained"
          color="default"
          size="small"
        >
          로그아웃
        </Button>
      );
    }

    return (
      <div className="User">
        <div className="UserButtons">
          <Button
            type="button"
            variant="contained"
            color="default"
            size="small"
            onClick={() => this.props.history.push('/bookbasket')}
            endIcon={<ShoppingBasketIcon />}
          >
            책바구니
          </Button>
          <Button
            type="button"
            variant="contained"
            color="default"
            size="small"
            onClick={() => this.props.history.push('/mypage')}
            endIcon={<PermIdentityIcon />}
          >
            {username}
          </Button>
          {logButton}
        </div>
        <div className="BookStoreLinkButtons">
          <Button
            type="button"
            onClick={() => window.open(
              'https://search.kyobobook.co.kr/web/search?vPstrKeyWord=%ED%95%9C%ED%8B%B0%EC%9E%AC&orderClick=LAW&searchPubCd=26867&searchPcondition=1',
            )}
            variant="contained"
            color="primary"
            size="small"
          >
            교보문고
          </Button>
          <Button
            type="button"
            onClick={() => window.open(
              'https://www.aladin.co.kr/search/wsearchresult.aspx?PublisherSearch=%c7%d1%c6%bc%c0%e7@48149&BranchType=1',
            )}
            variant="contained"
            color="primary"
            size="small"
          >
            알라딘
          </Button>
          <Button
            type="button"
            onClick={() => window.open(
              'http://www.yes24.com/SearchCorner/Search/List?detail_yn=Y&query=%uD55C%uD2F0%uC7AC&domain=BOOK&disp_no=&title=&theme=&author=&company=%uD55C%uD2F0%uC7AC&isbn=&sPrice=&ePrice=&sYear=&sMonth=1&eYear=&eMonth=1&scode=004',
            )}
            variant="contained"
            color="primary"
            size="small"
          >
            yes24
          </Button>
          <Button
            type="button"
            onClick={() => window.open(
              'http://bsearch.interpark.com/dsearch/book.jsp?sch=all&query=%C7%D1%C6%BC%C0%E7',
            )}
            variant="contained"
            color="primary"
            size="small"
          >
            인터파크
          </Button>
          {/* eslint-disable-next-line */}
          {/* <div className="BasketCount" >{bookCount}</div> */}
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state: any) => ({
  getMeStatus: state.user.getMeStatus,
  me: state.user.me,
  basket: state.user.basket,
});

const mapDispatchToProps = (dispatch: Dispatch<any>) => ({
  onGetMe: () => dispatch(userActions.getMe()),
  onLogout: () => dispatch(userActions.logout()),
});

export default connect(mapStateToProps, mapDispatchToProps)(User);
