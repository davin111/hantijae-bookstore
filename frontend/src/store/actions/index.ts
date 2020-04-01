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
} from './user/user';


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
};
