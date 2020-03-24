import { bookConstants } from '../../actions/actionTypes';
import { bookStatus } from '../../../constants/constants';

const initialState = {
  getBookStatus: bookStatus.NONE,
  books: [],
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case bookConstants.GET_BOOKS_SUCCESS:
      return { ...state, getBookStatus: bookStatus.SUCCESS, books: action.target };
    case bookConstants.GET_BOOKS_FAILURE:
      return { ...state, getBookStatus: bookStatus.FAILURE };
    default:
      return { ...state };
  }
};

export default reducer;
