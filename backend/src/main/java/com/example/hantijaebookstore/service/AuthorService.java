package com.example.hantijaebookstore.service;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.repository.AuthorRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;

@Service
public class AuthorService {
    @Autowired
    private AuthorRepository authorRepository;

    public AuthorService(AuthorRepository authorRepository) {
        this.authorRepository = authorRepository;
    }

    public Map serializeAuthor(Author author) {
        Map<String, Object> response = new HashMap<>();
        response.put("id", author.getId());
        response.put("familyName", author.getFamilyName());
        response.put("givenName", author.getGivenName());
        response.put("email", author.getEmail());
        response.put("address", author.getAddress());
        response.put("phoneNumber", author.getPhoneNumber());
        response.put("createdAt", author.getCreatedAt());
        response.put("updatedAt", author.getUpdatedAt());

        ArrayList<Book> books = new ArrayList<Book>();
        for (int i = 0; i < author.getBookAuthors().size(); i++) {
            books.add(author.getBookAuthors().get(i).getBook());
        }
        response.put("books", books);
        return response;
    }
}
