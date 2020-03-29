import axios from 'axios';
import { Dispatch } from 'redux';
import { bookConstants, categoryConstants } from '../actionTypes';

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

const getBooksFailure = (error: any) => ({
  type: bookConstants.GET_BOOKS_FAILURE,
  target: error,
});

export const getBooks = () => (dispatch: Dispatch) => axios.get('/api/book/')
  .then((res) => dispatch(getBooksSuccess(res.data)))
  .catch((err) => dispatch(getBooksFailure(err)));

const getBooksByCategorySuccess = (books: any) => ({
  type: bookConstants.GET_BOOKS_SUCCESS,
  target: books,
});

const getBooksByCategoryFailure = (error: any) => ({
  type: bookConstants.GET_BOOKS_FAILURE,
  target: error,
});

export const getBooksByCategory = (id: number) => (dispatch: Dispatch) => axios.get(`/api/category/${id}/book/`)
  .then((res) => dispatch(getBooksByCategorySuccess(res.data)))
  .catch((err) => dispatch(getBooksByCategoryFailure(err)));


const getCategoriesSuccess = (categories: any) => ({
  type: categoryConstants.GET_CATEGORIES_SUCCESS,
  target: categories,
});

const getCategoriesFailure = (error: any) => ({
  type: categoryConstants.GET_CATEGORIES_FAILURE,
  target: error,
});

export const getCategories = () => (dispatch: Dispatch) => axios.get('/api/book/category/')
  .then((res) => dispatch(getCategoriesSuccess(res.data)))
  .catch((err) => dispatch(getCategoriesFailure(err)));
