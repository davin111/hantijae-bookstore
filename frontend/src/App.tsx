import React from 'react';
import { Route, Switch } from 'react-router-dom';
import { ConnectedRouter } from 'connected-react-router';

import {
  Header, Auth, Footer, LeaveSpa,
} from './components';
import {
  LoginPage, SignupPage, BookBasket, MyPage,
} from './containers';

import './App.css';

interface Props {
  history: any;
}

// 공개 화면은 Django(web 앱)가 서버에서 그린다. React는 회원 화면 네 개만 맡는다(nginx가 이 네 경로만 보냄).
function App(props: Props): JSX.Element {
  return (
    <div className="App">
      <ConnectedRouter history={props.history}>
        <Auth history={props.history} />
        <Header />
        <Switch>
          <Route path="/login" exact component={LoginPage} history={props.history} />
          <Route path="/signup" exact component={SignupPage} history={props.history} />
          <Route path="/bookbasket" exact component={BookBasket} history={props.history} />
          <Route path="/mypage" exact component={MyPage} history={props.history} />
          <Route component={LeaveSpa} />
        </Switch>
        <Footer />
      </ConnectedRouter>
    </div>
  );
}

export default App;
