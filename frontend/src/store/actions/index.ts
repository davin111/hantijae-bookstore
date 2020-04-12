import {
  getBook,
  getBooks,
  searchBooks,
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
  orderBasket,
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
};

export const userActions = {
  login,
  logout,
  signup,
  getMe,
  postBookInBasket,
  putBookInBasket,
  getBasket,
  orderBasket,
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
