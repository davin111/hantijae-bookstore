package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.model.BookAuthor;
import com.example.hantijaebookstore.repository.AuthorRepository;
import com.example.hantijaebookstore.repository.BookAuthorRepository;
import com.example.hantijaebookstore.repository.BookRepository;
import com.example.hantijaebookstore.service.AuthorService;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@AllArgsConstructor
@RequestMapping("api/author/")
@RestController
public class AuthorController {

    private AuthorRepository authorRepository;

    private AuthorService authorService;

    private BookRepository bookRepository;

    private BookAuthorRepository bookAuthorRepository;

    @PostMapping
    public ResponseEntity addAuthor(@Valid @NotNull @RequestBody Author author) {
        authorRepository.save(author);
        return new ResponseEntity(author, HttpStatus.CREATED);
    }

    @ResponseBody
    @GetMapping
    public ArrayList<Map<String, Object>> getAllAuthor() {
        List<Author> authors = authorRepository.findAll();
        ArrayList<Map<String, Object>> response = new ArrayList<>();
        for (int i = 0; i < authors.size(); i++) {
            response.add(authorService.serializeAuthor(authors.get(i)));
        }
        return response;
    }

    @ResponseBody
    @GetMapping(path = "{id}")
    public Map<String, Object> getAuthorById(@PathVariable("id") int id) {
        Author author = authorRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return authorService.serializeAuthor(author);
    }

    @DeleteMapping(path = "{id}")
    public void deleteAuthorById(@PathVariable("id") int id) {
        Author author = authorRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        authorRepository.delete(author);
    }

    @PutMapping(path = "{id}")
    public ResponseEntity updateAuthorById(@PathVariable("id") int id, @NotNull @RequestBody Author newAuthor) {
        Author author = authorRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        author.setFamilyName(newAuthor.getFamilyName());
        author.setGivenName(newAuthor.getGivenName());
        author.setEmail(newAuthor.getEmail());
        author.setAddress(newAuthor.getAddress());
        author.setPhoneNumber(newAuthor.getPhoneNumber());
        return new ResponseEntity(author, HttpStatus.OK);
    }

    @PutMapping(path = "{id}/book/{bookId}")
    public void relateAuthorBook(@PathVariable("id") int id, @PathVariable("bookId") int bookId) {
        Author author = authorRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        Book book = bookRepository.findById(bookId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        BookAuthor bookAuthor = new BookAuthor(book, author);
        bookAuthorRepository.save(bookAuthor);

        author.getBookAuthors().add(bookAuthor);
    }
}
