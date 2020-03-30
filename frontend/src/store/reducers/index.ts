import { combineReducers } from 'redux';
import { connectRouter } from 'connected-react-router';
import bookReducer from './book/book';
import userReducer from './user/user';

const rootReducer = (history: any) => combineReducers({
  book: bookReducer,
  user: userReducer,
  router: connectRouter(history),
});
export default rootReducer;
