import axios from 'axios';
import { Dispatch } from 'redux';
import { userConstants, basketActions } from '../actionTypes';

const loginSuccess = (user: any) => ({
  type: userConstants.LOGIN_SUCCESS,
  target: user,
});

const loginFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 403:
      actionType = userConstants.LOGIN_FAILURE;
      break;
    default:
      actionType = userConstants.LOGIN_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const login = (
  username: string, password: string,
) => (dispatch: Dispatch) => axios.put('/api/user/login/', { username, password })
  .then((res) => dispatch(loginSuccess(res.data)))
  .catch((err) => dispatch(loginFailure(err)));

const logoutSuccess = () => ({
  type: userConstants.LOGOUT_SUCCESS,
  target: null,
});

const logoutFailure = (error: any) => ({
  type: userConstants.LOGOUT_FAILURE,
  target: error,
});

export const logout = () => (dispatch: Dispatch) => axios.get('/api/user/logout/')
  .then((res) => dispatch(logoutSuccess()))
  .catch((err) => dispatch(logoutFailure(err)));


const signupSuccess = (user: any) => ({
  type: userConstants.SIGNUP_SUCCESS,
  target: user,
});

const signupFailure = (error: any) => ({
  type: userConstants.SIGNUP_FAILURE,
  target: error,
});

export const signup = (
  username: string, email: string, password: string,
) => (dispatch: Dispatch) => axios.post('/api/user/signup/')
  .then((res) => dispatch(signupSuccess(res.data)))
  .catch((err) => dispatch(signupFailure(err)));


const getMeSuccess = (user: any) => ({
  type: userConstants.GET_ME_SUCCESS,
  target: user,
});

const getMeFailure = (error: any) => ({
  type: userConstants.GET_ME_FAILURE,
  target: error,
});

export const getMe = () => (dispatch: Dispatch) => axios.get('/api/user/me')
  .then((res) => dispatch(getMeSuccess(res.data)))
  .catch((err) => dispatch(getMeFailure(err)));


const postBookInBasketSuccess = (basket: any) => ({
  type: basketActions.POST_BOOK_SUCCESS,
  target: basket,
});

const postBookInBasketFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 406:
      actionType = basketActions.POST_BOOK_FAILURE_MAX_BOOK;
      break;
    default:
      actionType = basketActions.POST_BOOK_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const postBookInBasket = (id: number, count: number) => (dispatch: Dispatch) => axios.post('/api/user/basket/book/', { book: id, count })
  .then((res) => dispatch(postBookInBasketSuccess(res.data)))
  .catch((err) => dispatch(postBookInBasketFailure(err)));


const getBasketSuccess = (basket: any) => ({
  type: basketActions.GET_BASKET_SUCCESS,
  target: basket,
});

const getBasketFailure = (error: any) => ({
  type: basketActions.GET_BASKET_FAILURE,
  target: error,
});

export const getBasket = () => (dispatch: Dispatch) => axios.get('/api/user/basket')
  .then((res) => dispatch(getBasketSuccess(res.data)))
  .catch((err) => dispatch(getBasketFailure(err)));
