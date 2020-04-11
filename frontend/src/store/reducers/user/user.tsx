import { userConstants, basketActions } from '../../actions/actionTypes';
import { userStatus, basketStatus } from '../../../constants/constants';

const initialState = {
  me: {},
  basket: {
    id: 0,
    bookCount: 0,
    maxBookCount: 0,
    totalPrice: 0,
    maxPrice: 0,
    books: [],
  },
  orders: {},
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
          familyName: data.family_name,
          givenName: data.given_name,
          id: data.id,
          lastLogin: data.last_login,
          anonymous: data.anonymous,
          notifiable: data.notifiable,
        },
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case userConstants.LOGIN_FAILURE:
    case userConstants.LOGOUT_FAILURE:
      return { ...state, loginStatus: userStatus.FAILURE };
    case userConstants.LOGOUT_SUCCESS:
      return { ...state, logoutStatus: userStatus.SUCCESS };
    case userConstants.SIGNUP_SUCCESS:
      return {
        ...state,
        signupStatus: userStatus.SUCCESS,
        me: {
          username: data.username,
          email: data.email,
          familyName: data.family_name,
          givenName: data.given_name,
          id: data.id,
          lastLogin: data.last_login,
          anonymous: data.anonymous,
          notifiable: data.notifiable,
        },
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case userConstants.SIGNUP_FAILURE:
      return { ...state, signupStatus: userStatus.FAILURE };
    case userConstants.SIGNUP_FAILURE_USERNAME:
      return { ...state, signupStatus: userStatus.FAILURE_USERNAME };
    case userConstants.GET_ME_SUCCESS:
      return {
        ...state,
        getMeStatus: userStatus.SUCCESS,
        me: {
          username: data.username,
          email: data.email,
          familyName: data.family_name,
          givenName: data.given_name,
          id: data.id,
          lastLogin: data.last_login,
          anonymous: data.anonymous,
          notifiable: data.notifiable,
        },
        basket: { ...state.basket, bookCount: data.book_count },
      };
    case userConstants.GET_ME_FAILURE:
      return {
        ...state, getMeStatus: userStatus.FAILURE, me: {}, basket: {},
      };
    case basketActions.POST_BOOK_SUCCESS:
    case basketActions.PUT_BOOK_SUCCESS:
    case basketActions.GET_BASKET_SUCCESS:
    case basketActions.PUT_ORDER_SUCCESS:
      return {
        ...state,
        basketStatus: basketStatus.SUCCESS,
        basket: {
          ...state.basket,
          id: data.id,
          bookCount: data.book_count,
          maxBookCount: data.max_book_count,
          totalPrice: data.total_price,
          maxPrice: data.max_price,
          status: data.status,
          books: data.books,
        },
      };
    case basketActions.POST_BOOK_FAILURE:
    case basketActions.PUT_BOOK_FAILURE:
    case basketActions.GET_BASKET_FAILURE:
    case basketActions.PUT_ORDER_FAILURE:
    case basketActions.GET_ORDERS_FAILURE:
      return {
        ...state,
        basketStatus: basketStatus.FAILURE,
      };
    case basketActions.POST_BOOK_FAILURE_MAX_BOOK:
    case basketActions.PUT_BOOK_FAILURE_MAX_BOOK:
      return {
        ...state,
        basketStatus: basketStatus.FAILURE_MAX_BOOK,
      };
    case basketActions.GET_ORDERS_SUCCESS:
      return {
        ...state,
        basketStatus: basketStatus.SUCCESS,
        orders: data,
      };
    default:
      return { ...state };
  }
};

export default reducer;
