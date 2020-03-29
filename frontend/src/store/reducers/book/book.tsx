import { bookConstants, categoryConstants } from '../../actions/actionTypes';
import { bookStatus, categoryStatus } from '../../../constants/constants';

const initialState = {
  getBookStatus: bookStatus.NONE,
  getCategoryStatus: categoryStatus.NONE,
  books: {},
  getBooksByCategories: {},
  getCategories: {},
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
    default:
      return { ...state };
  }
};

export default reducer;
