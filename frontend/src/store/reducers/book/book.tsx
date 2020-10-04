import { bookConstants, categoryConstants, seriesConstants } from '../../actions/actionTypes';
import { bookStatus, categoryStatus, seriesStatus } from '../../../constants/constants';

const initialState = {
  getBookStatus: bookStatus.NONE,
  getCategoryStatus: categoryStatus.NONE,
  getSeriesStatus: seriesStatus.NONE,
  searchBooksStatus: bookStatus.NONE,
  books: {},
  getBook: {},
  getBooksByCategories: {},
  getCategories: {},
  getSeries: {},
  getAllSeries: {},
  activeSeriesId: 0,
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case bookConstants.GET_BOOK_SUCCESS:
      return { ...state, getBookStatus: bookStatus.SUCCESS, getBook: action.target };
    case bookConstants.GET_BOOK_FAILURE:
    case bookConstants.GET_BOOKS_FAILURE:
      return { ...state, getBookStatus: bookStatus.FAILURE };
    case bookConstants.GET_BOOKS_SUCCESS:
      return { ...state, getBookStatus: bookStatus.SUCCESS, books: action.target };
    case bookConstants.SEARCH_BOOKS_SUCCESS:
      return { ...state, searchBooksStatus: bookStatus.SUCCESS, books: action.target };
    case bookConstants.SEARCH_BOOKS_FAILURE:
      return { ...state, searchBooksStatus: bookStatus.FAILURE };
    case bookConstants.GET_BOOKS_BY_CATEGORY_SUCCESS:
      return { ...state, getBooksByCategories: action.target };
    case categoryConstants.GET_CATEGORIES_SUCCESS:
      return { ...state, getCategoryStatus: categoryStatus.SUCCESS, getCategories: action.target };
    case categoryConstants.GET_CATEGORIES_FAILURE:
      return { ...state, getCategoryStatus: categoryStatus.FAILURE };
    case seriesConstants.GET_SERIES_SUCCESS:
      return { ...state, getSeriesStatus: seriesStatus.SUCCESS, getSeries: action.target };
    case seriesConstants.GET_SERIES_FAILURE:
    case seriesConstants.GET_ALL_SERIES_FAILURE:
      return { ...state, getSeriesStatus: seriesStatus.FAILURE };
    case seriesConstants.GET_ALL_SERIES_SUCCESS:
      return { ...state, getSeriesStatus: seriesStatus.SUCCESS, getAllSeries: action.target };
    case seriesConstants.CHANGE_ACTIVE_SERIES:
      return { ...state, activeSeriesId: action.target };
    default:
      return { ...state };
  }
};

export default reducer;
