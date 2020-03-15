import { combineReducers } from 'redux';
import { connectRouter } from 'connected-react-router';
import bookReducer from './book/book';

const rootReducer = (history: any) => combineReducers({
  book: bookReducer,
  router: connectRouter(history),
});
export default rootReducer;
