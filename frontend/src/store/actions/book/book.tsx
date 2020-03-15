import axios from 'axios';
import { Dispatch } from 'redux';
import { bookConstants } from '../actionTypes';

const getBookSuccess = (book: any) => ({
  type: bookConstants.GET_BOOK_SUCCESS,
  target: book.book,
});

const getBookFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 404:
      actionType = bookConstants.GET_BOOK_FAILURE;
      break;
    default:
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const getBook = (bookId: string) => (dispatch: Dispatch) => axios.get('/api/book/', { params: bookId })
  .then((res) => dispatch(getBookSuccess(res.data)))
  .catch((err) => dispatch(getBookFailure(err)));


const getBooksSuccess = (books: any) => ({
  type: bookConstants.GET_BOOKS_SUCCESS,
  target: books,
});

const getBooksFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 404:
      actionType = bookConstants.GET_BOOKS_FAILURE;
      break;
    default:
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const getBooks = () => (dispatch: Dispatch) => axios.get('/api/book/')
  .then((res) => dispatch(getBooksSuccess(res.data)))
  .catch((err) => dispatch(getBooksFailure(err)));
