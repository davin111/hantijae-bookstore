import {
  getBook,
  getBooks,
  searchBooks,
  getBooksByCategory,
  getCategories,
  getSeries,
  getAllSeries,
  changeActiveSeries,
} from './book/book';

import {
  login,
  logout,
  signup,
  getMe,
  postBookInBasket,
  postBookInBasket202006NewBook,
  putBookInBasket,
  putBookInBasket202006NewBook,
  getBasket,
  getBasket202006NewBook,
  orderBasket,
  orderBasket202006NewBook,
  getOrders,
} from './user/user';

import {
  openLoginModal,
  closeLoginModal,
  openFullBasketModal,
  closeFullBasketModal,
  openBasketInfoModal,
  closeBasketInfoModal,
  dontSuggestLogin,
  openEventModal,
  closeEventModal,
} from './state/state';


export const bookActions = {
  getBook,
  getBooks,
  searchBooks,
  getBooksByCategory,
  getCategories,
  getSeries,
  getAllSeries,
  changeActiveSeries,
};

export const userActions = {
  login,
  logout,
  signup,
  getMe,
  postBookInBasket,
  postBookInBasket202006NewBook,
  putBookInBasket,
  putBookInBasket202006NewBook,
  getBasket,
  getBasket202006NewBook,
  orderBasket,
  orderBasket202006NewBook,
  getOrders,
};

export const stateActions = {
  openLoginModal,
  closeLoginModal,
  openFullBasketModal,
  closeFullBasketModal,
  openBasketInfoModal,
  closeBasketInfoModal,
  dontSuggestLogin,
  openEventModal,
  closeEventModal,
};
