package com.example.hantijaebookstore.dao;

import com.example.hantijaebookstore.model.Book;
import org.springframework.stereotype.Repository;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@Repository("fakeDaoBook")
public class FakeBookDataAccessService implements BookDao {
    private int lastId = 0;
    private static List<Book> DB = new ArrayList<>();

    @Override
    public int insertBook(Book book) {
        int id = this.lastId;
        this.lastId += 1;

        DB.add(new Book(id, book.getTitle(), book.getDescription()));
        return 1;
    }

    @Override
    public List<Book> selectAllBook() {
        return DB;
    }

    @Override
    public Optional<Book> selectBookById(int id) {
        return DB.stream()
                .filter(user -> user.getId() == id)
                .findFirst();
    }

    @Override
    public int deleteBookById(int id) {
        Optional<Book> userMaybe = selectBookById(id);
        if (userMaybe.isEmpty()) {
            return 0;
        }
        DB.remove(userMaybe.get());
        return 1;
    }

    @Override
    public int updateBookById(int id, Book update) {
        return selectBookById(id)
                .map(book -> {
                    int indexOfBookToUpdate = DB.indexOf(book);
                    if (indexOfBookToUpdate >= 0) {
                        DB.set(indexOfBookToUpdate, new Book(id, update.getTitle(), update.getDescription()));
                        return 1;
                    }
                    return 0;
                })
                .orElse(0);
    }
}
