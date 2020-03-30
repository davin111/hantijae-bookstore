import React from 'react';
import { Route, Switch } from 'react-router-dom';
import { ConnectedRouter } from 'connected-react-router';

import { Header } from './components';
import { Main, BookDetail, Login } from './containers';

import './App.css';

interface Props {
  history: any;
}

function App(props: Props): JSX.Element {
  const { history } = props;
  return (
    <div className="App">
      <ConnectedRouter history={history}>
        <Header history={props.history} />
        <Switch>
          <Route path="/login" exact component={Login} history={props.history} />
          <Route path="/" exact component={Main} history={props.history} />
          <Route path="/series=:series_id" exact component={Main} history={props.history} />
          <Route path="/book=:book_id" exact component={BookDetail} history={props.history} />
        </Switch>
      </ConnectedRouter>
    </div>
  );
}

export default App;
