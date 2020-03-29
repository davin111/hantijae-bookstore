package com.example.hantijaebookstore.service;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.repository.AuthorRepository;
import com.example.hantijaebookstore.repository.BookRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class BookService {
    @Autowired
    private BookRepository bookRepository;

    public BookService(BookRepository bookRepository) {
        this.bookRepository = bookRepository;
    }

    public Map serializeBook(Book book) {
        Map<String, Object> response = new HashMap<>();
        response.put("id", book.getId());
        response.put("title", book.getTitle());
        response.put("subtitle", book.getSubtitle());
        response.put("shortDescription", book.getShortDescription());
        response.put("description", book.getDescription());
        response.put("fullPrice", book.getFullPrice());
        response.put("price", book.getPrice());
        response.put("isbn", book.getISBN());
        response.put("pageCount", book.getPageCount());
        response.put("size", book.getSize());
        response.put("extraURL", book.getExtraURL());
        response.put("ebookURL", book.getEbookURL());
        response.put("createdAt", book.getCreatedAt());
        response.put("updatedAt", book.getUpdatedAt());

        List<Author> authors = new ArrayList<Author>();
        for (int i = 0; i < book.getBookAuthors().size(); i++) {
            authors.add(book.getBookAuthors().get(i).getAuthor());
        }
        response.put("authors", authors);
        return response;
    }

    public List<Map> serializeBooks(List<Book> books) {
        List<Map> response = new ArrayList<>();
        for (int i = 0; i < books.size(); i++) {
            response.add(serializeBook(books.get(i)));
        }
        return response;
    }
}
