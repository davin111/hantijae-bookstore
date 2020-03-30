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
  signup,
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
  signup,
};
