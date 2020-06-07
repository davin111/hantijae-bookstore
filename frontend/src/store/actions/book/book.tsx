import axios from 'axios';
import { Dispatch } from 'redux';
import { bookConstants, categoryConstants, seriesConstants } from '../actionTypes';

const getBookSuccess = (book: any) => ({
  type: bookConstants.GET_BOOK_SUCCESS,
  target: book,
});

const getBookFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 404:
      actionType = bookConstants.GET_BOOK_FAILURE;
      break;
    default:
      actionType = bookConstants.GET_BOOK_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const getBook = (id: number) => (dispatch: Dispatch) => axios.get(`/api/book/${id}/`)
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


const searchBooksSuccess = (books: any) => ({
  type: bookConstants.GET_BOOKS_SUCCESS,
  target: books,
});

const searchBooksFailure = (error: any) => ({
  type: bookConstants.GET_BOOKS_FAILURE,
  target: error,
});

export const searchBooks = (search: string) => (dispatch: Dispatch) => axios.get('/api/book/', { params: { search } })
  .then((res) => dispatch(searchBooksSuccess(res.data)))
  .catch((err) => dispatch(searchBooksFailure(err)));


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


const getSeriesSuccess = (series: any) => ({
  type: seriesConstants.GET_SERIES_SUCCESS,
  target: series,
});

const getSeriesFailure = (error: any) => ({
  type: seriesConstants.GET_ALL_SERIES_FAILURE,
  target: error,
});

export const getSeries = (id: number) => (dispatch: Dispatch) => axios.get(`/api/book/series/${id}/`)
  .then((res) => dispatch(getSeriesSuccess(res.data)))
  .catch((err) => dispatch(getSeriesFailure(err)));


const getAllSeriesSuccess = (series: any) => ({
  type: seriesConstants.GET_ALL_SERIES_SUCCESS,
  target: series,
});

const getAllSeriesFailure = (error: any) => ({
  type: seriesConstants.GET_ALL_SERIES_FAILURE,
  target: error,
});

export const getAllSeries = () => (dispatch: Dispatch) => axios.get('/api/book/series/')
  .then((res) => dispatch(getAllSeriesSuccess(res.data)))
  .catch((err) => dispatch(getAllSeriesFailure(err)));
