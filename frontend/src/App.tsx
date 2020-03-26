import React from 'react';
import { Route, Switch } from 'react-router-dom';
import { ConnectedRouter } from 'connected-react-router';

import { Header } from './components';
import { Main } from './containers';

import './App.css';

interface Props {
  history: any;
}

function App(props: Props): JSX.Element {
  const { history } = props;
  return (
    <div className="App">
      <ConnectedRouter history={history}>
        <Header />
        <Switch>
          <Route path="/" exact component={Main} />
        </Switch>
      </ConnectedRouter>
    </div>
  );
}

export default App;
