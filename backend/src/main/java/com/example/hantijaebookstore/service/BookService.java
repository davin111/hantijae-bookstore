package com.example.hantijaebookstore.service;

import com.example.hantijaebookstore.dao.BookDao;
import com.example.hantijaebookstore.model.Book;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class BookService {

    private final BookDao bookDao;

    @Autowired
    public BookService(@Qualifier("fakeDaoBook") BookDao bookDao) {
        this.bookDao = bookDao;
    }

    public int addBook(Book book) {
        return bookDao.insertBook(book);
    }

    public List<Book> getAllBook() {
        return bookDao.selectAllBook();
    }

    public Optional<Book> getBookById(int id) {
        return bookDao.selectBookById(id);
    }

    public int deleteBook(int id) {
        return bookDao.deleteBookById(id);
    }

    public int updateBook(int id, Book newBook) {
        return bookDao.updateBookById(id, newBook);
    }
}
