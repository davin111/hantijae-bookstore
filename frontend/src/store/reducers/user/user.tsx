import { userConstants, basketActions } from '../../actions/actionTypes';
import { userStatus, basketStatus } from '../../../constants/constants';

const initialState = {
  me: {},
  basket: {
    bookCount: 0,
    books: [],
  },
  getMeStatus: userStatus.NONE,
  loginStatus: userStatus.NONE,
  logoutStatus: userStatus.NONE,
  signupStatus: userStatus.NONE,
  basketStatus: basketStatus.NONE,
};

const reducer = (state = initialState, action: any) => {
  const data = action.target;
  switch (action.type) {
    case userConstants.LOGIN_SUCCESS:
      return {
        ...state,
        loginStatus: userStatus.SUCCESS,
        me: {
          username: data.username,
          email: data.email,
          id: data.id,
          lastLogin: data.last_login,
          anonymous: data.anonymous,
        },
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case userConstants.LOGIN_FAILURE:
    case userConstants.LOGOUT_FAILURE:
      return { ...state, loginStatus: userStatus.FAILURE };
    case userConstants.LOGOUT_SUCCESS:
      return { ...state, logoutStatus: userStatus.SUCCESS };
    case userConstants.SIGNUP_SUCCESS:
      return { ...state, signupStatus: userStatus.SUCCESS };
    case userConstants.SIGNUP_FAILURE:
      return { ...state, signupStatus: userStatus.FAILURE };
    case userConstants.GET_ME_SUCCESS:
      return {
        ...state,
        getMeStatus: userStatus.SUCCESS,
        me: {
          username: data.username,
          email: data.email,
          id: data.id,
          lastLogin: data.last_login,
          anonymous: data.anonymous,
        },
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case userConstants.GET_ME_FAILURE:
      return {
        ...state, getMeStatus: userStatus.FAILURE, me: {}, basket: {},
      };
    case basketActions.POST_BOOK_SUCCESS:
      return {
        ...state,
        basketStatus: basketStatus.SUCCESS,
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case basketActions.POST_BOOK_FAILURE:
    case basketActions.GET_BASKET_FAILURE:
      return {
        ...state,
        basketStatus: basketStatus.FAILURE,
      };
    case basketActions.POST_BOOK_FAILURE_MAX_BOOK:
      return {
        ...state,
        basketStatus: basketStatus.FAILURE_MAX_BOOK,
      };
    case basketActions.GET_BASKET_SUCCESS:
      return {
        ...state,
        basketStatus: basketStatus.SUCCESS,
        basket: {
          ...state.basket,
          bookCount: data.book_count,
          maxBookCount: data.max_book_count,
          maxPrice: data.max_price,
          status: data.status,
          books: data.books,
        },
      };
    default:
      return { ...state };
  }
};

export default reducer;
