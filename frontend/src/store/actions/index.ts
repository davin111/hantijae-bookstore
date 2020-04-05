import {
  getBook,
  getBooks,
  getBooksByCategory,
  getCategories,
  getSeries,
  getAllSeries,
} from './book/book';

import {
  login,
  logout,
  signup,
  getMe,
  postBookInBasket,
  putBookInBasket,
  getBasket,
} from './user/user';

import {
  openLoginModal,
  closeLoginModal,
  openFullBasketModal,
  closeFullBasketModal,
  openBasketInfoModal,
  closeBasketInfoModal,
} from './state/state';


export const bookActions = {
  getBook,
  getBooks,
  getBooksByCategory,
  getCategories,
  getSeries,
  getAllSeries,
};

export const userActions = {
  login,
  logout,
  signup,
  getMe,
  postBookInBasket,
  putBookInBasket,
  getBasket,
};

export const stateActions = {
  openLoginModal,
  closeLoginModal,
  openFullBasketModal,
  closeFullBasketModal,
  openBasketInfoModal,
  closeBasketInfoModal,
};
