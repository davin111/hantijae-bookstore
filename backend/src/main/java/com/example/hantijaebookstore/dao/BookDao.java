package com.example.hantijaebookstore.dao;

import com.example.hantijaebookstore.model.Book;

import java.util.List;
import java.util.Optional;

public interface BookDao {
    int insertBook(Book book);

    List<Book> selectAllBook();

    Optional<Book> selectBookById(int id);

    int deleteBookById(int id);

    int updateBookById(int id, Book book);
}
