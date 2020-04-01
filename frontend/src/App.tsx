import React from 'react';
import { Route, Switch, Redirect } from 'react-router-dom';
import { ConnectedRouter } from 'connected-react-router';

import { Header, Auth } from './components';
import {
  Main, BookDetail, Login, Signup,
} from './containers';


import './App.css';

interface Props {
  history: any;
}

function App(props: Props): JSX.Element {
  return (
    <div className="App">
      <ConnectedRouter history={props.history}>
        <Auth history={props.history} />
        <Header history={props.history} />
        <Switch>
          <Route path="/login" exact component={Login} history={props.history} />
          <Route path="/signup" exact component={Signup} history={props.history} />
          <Route path="/" exact component={Main} history={props.history} />
          <Route path="/series=:series_id" exact component={Main} history={props.history} />
          <Route path="/book=:book_id" exact component={BookDetail} history={props.history} />
          <Redirect exact to="/" />
        </Switch>
      </ConnectedRouter>
    </div>
  );
}

export default App;
