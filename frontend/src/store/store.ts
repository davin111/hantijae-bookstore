import { createStore, applyMiddleware } from 'redux';
import thunk from 'redux-thunk';
import { routerMiddleware } from 'connected-react-router';
import { createBrowserHistory } from 'history';

import rootReducer from './reducers/index';

export const history = createBrowserHistory();
export const middlewares = [thunk, routerMiddleware(history)];

const store = createStore(rootReducer(history), applyMiddleware(...middlewares));

export default store;
