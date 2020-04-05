import { combineReducers } from 'redux';
import { connectRouter } from 'connected-react-router';
import bookReducer from './book/book';
import userReducer from './user/user';
import stateReducer from './state/state';

const rootReducer = (history: any) => combineReducers({
  book: bookReducer,
  user: userReducer,
  state: stateReducer,
  router: connectRouter(history),
});
export default rootReducer;
