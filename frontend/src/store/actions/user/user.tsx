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

const signupFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 406:
      actionType = userConstants.SIGNUP_FAILURE_USERNAME;
      break;
    default:
      actionType = userConstants.SIGNUP_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const signup = (
  username: string, email: string, password: string,
  familyName: string, givenName: string, notifiable: boolean,
) => (dispatch: Dispatch) => axios.post('/api/user/', {
  username, email, password, family_name: familyName, given_name: givenName, notifiable,
})
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


const putBookInBasketSuccess = (basket: any) => ({
  type: basketActions.PUT_BOOK_SUCCESS,
  target: basket,
});

const putBookInBasketFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 406:
      actionType = basketActions.PUT_BOOK_FAILURE_MAX_BOOK;
      break;
    default:
      actionType = basketActions.PUT_BOOK_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const putBookInBasket = (bookId: number, count: number, basketId: number) => (dispatch: Dispatch) => axios.put('/api/user/basket/book/', { book: bookId, count, basket: basketId })
  .then((res) => dispatch(putBookInBasketSuccess(res.data)))
  .catch((err) => dispatch(putBookInBasketFailure(err)));


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


const orderBasketSuccess = (basket: any) => ({
  type: basketActions.PUT_ORDER_SUCCESS,
  target: basket,
});

const orderBasketFailure = (error: any) => ({
  type: basketActions.PUT_ORDER_FAILURE,
  target: error,
});

export const orderBasket = (basketId: number, familyName: string, givenName: string, email: string,
  phoneNumber: string, receiverFamilyName: string, receiverGivenName: string,
  address: string, postalCode: string, payer: string) => (dispatch: Dispatch) => axios.put(
  '/api/user/basket/order/', {
    basket: basketId,
    family_name: familyName,
    given_name: givenName,
    email,
    phone_number: phoneNumber,
    receiver_family_name: receiverFamilyName,
    receiver_given_name: receiverGivenName,
    address,
    postal_code: postalCode,
    payer,
  },
)
  .then((res) => dispatch(orderBasketSuccess(res.data)))
  .catch((err) => dispatch(orderBasketFailure(err)));


const getOrdersSuccess = (basket: any) => ({
  type: basketActions.GET_ORDERS_SUCCESS,
  target: basket,
});

const getOrdersFailure = (error: any) => ({
  type: basketActions.GET_ORDERS_FAILURE,
  target: error,
});

export const getOrders = () => (dispatch: Dispatch) => axios.get('/api/user/basket/order')
  .then((res) => dispatch(getOrdersSuccess(res.data)))
  .catch((err) => dispatch(getOrdersFailure(err)));
