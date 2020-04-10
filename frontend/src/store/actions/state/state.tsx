import { Dispatch } from 'redux';

import { stateActions } from '../actionTypes';

const openLoginModalSuccess = () => ({
  type: stateActions.OPEN_LOGIN_MODAL,
  target: true,
});

export const openLoginModal = () => (dispatch: Dispatch) => dispatch(openLoginModalSuccess());

const closeLoginModalSuccess = () => ({
  type: stateActions.CLOSE_LOGIN_MODAL,
  target: false,
});

export const closeLoginModal = () => (dispatch: Dispatch) => dispatch(closeLoginModalSuccess());


const openFullBasketModalSuccess = () => ({
  type: stateActions.OPEN_FULL_BASKET_MODAL,
  target: true,
});

export const openFullBasketModal = () => (dispatch: Dispatch) => dispatch(
  openFullBasketModalSuccess(),
);

const closeFullBasketModalSuccess = () => ({
  type: stateActions.CLOSE_FULL_BASKET_MODAL,
  target: false,
});

export const closeFullBasketModal = () => (dispatch: Dispatch) => dispatch(
  closeFullBasketModalSuccess(),
);


const openBasketInfoModalSuccess = () => ({
  type: stateActions.OPEN_BASKET_INFO_MODAL,
  target: true,
});

export const openBasketInfoModal = () => (dispatch: Dispatch) => dispatch(
  openBasketInfoModalSuccess(),
);

const closeBasketInfoModalSuccess = () => ({
  type: stateActions.CLOSE_BASKET_INFO_MODAL,
  target: false,
});

export const closeBasketInfoModal = () => (dispatch: Dispatch) => dispatch(
  closeBasketInfoModalSuccess(),
);


const dontSuggestLoginSuccess = () => ({
  type: stateActions.DONT_SUGGEST_LOGIN,
  target: false,
});

export const dontSuggestLogin = () => (dispatch: Dispatch) => dispatch(
  dontSuggestLoginSuccess(),
);
