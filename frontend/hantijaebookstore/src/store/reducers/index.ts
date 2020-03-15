import { combineReducers } from 'redux';
import bookReducer from "./book/book";
import { connectRouter } from 'connected-react-router';

const rootReducer = (history: any) => combineReducers({
    book: bookReducer,
    router: connectRouter(history),
});
export default rootReducer;
