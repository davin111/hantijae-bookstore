import { bookConstants, categoryConstants, seriesConstants } from '../../actions/actionTypes';
import { bookStatus, categoryStatus, seriesStatus } from '../../../constants/constants';

const initialState = {
  getBookStatus: bookStatus.NONE,
  getCategoryStatus: categoryStatus.NONE,
  getSeriesStatus: seriesStatus.NONE,
  books: {},
  getBooksByCategories: {},
  getCategories: {},
  getAllSeries: {},
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case bookConstants.GET_BOOKS_SUCCESS:
      return { ...state, getBookStatus: bookStatus.SUCCESS, books: action.target };
    case bookConstants.GET_BOOKS_FAILURE:
      return { ...state, getBookStatus: bookStatus.FAILURE };
    case bookConstants.GET_BOOKS_BY_CATEGORY_SUCCESS:
      return { ...state, getBooksByCategories: action.target };
    case categoryConstants.GET_CATEGORIES_SUCCESS:
      return { ...state, getCategoryStatus: categoryStatus.SUCCESS, getCategories: action.target };
    case categoryConstants.GET_CATEGORIES_FAILURE:
      return { ...state, getCategoryStatus: categoryStatus.FAILURE };
    case seriesConstants.GET_ALL_SERIES_SUCCESS:
      return { ...state, getSeriesStatus: seriesStatus.SUCCESS, getAllSeries: action.target };
    case seriesConstants.GET_ALL_SERIES_FAILURE:
      return { ...state, getSeriesStatus: seriesStatus.FAILURE };
    default:
      return { ...state };
  }
};

export default reducer;
