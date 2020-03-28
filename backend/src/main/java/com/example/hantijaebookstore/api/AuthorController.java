package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.model.BookAuthor;
import com.example.hantijaebookstore.repository.AuthorRepository;
import com.example.hantijaebookstore.repository.BookAuthorRepository;
import com.example.hantijaebookstore.repository.BookRepository;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@AllArgsConstructor
@RequestMapping("api/author/")
@RestController
public class AuthorController {

    private AuthorRepository authorRepository;

    private BookRepository bookRepository;

    private BookAuthorRepository bookAuthorRepository;

    @PostMapping
    public ResponseEntity addAuthor(@Valid @NotNull @RequestBody Author author) {
        authorRepository.save(author);
        return new ResponseEntity(author, HttpStatus.CREATED);
    }

    @GetMapping
    public List<Author> getAllAuthor() {
        return authorRepository.findAll();
    }

    @ResponseBody
    @GetMapping(path = "{id}")
    public Map<String, Object> getAuthorById(@PathVariable("id") int id) {
        Author author = authorRepository.findById(id)
                .orElse(null);
        Map<String, Object> response = new HashMap<>();
        response.put("id", author.getId());
        response.put("familyName", author.getFamilyName());
        response.put("givenName", author.getGivenName());
        response.put("email", author.getEmail());
        response.put("address", author.getAddress());
        response.put("phoneNumber", author.getPhoneNumber());
        ArrayList<Book> books = new ArrayList<Book>();
        for (int i = 0; i < author.getBooks().size(); i++) {
            //books.add(author.getBooks().getBook().get(i));
        }
        response.put("books", books);
        response.put("createdAt", author.getCreatedAt());
        response.put("updatedAt", author.getUpdatedAt());
        return response;
    }

    @DeleteMapping(path = "{id}")
    public void deleteAuthorById(@PathVariable("id") int id) {
        authorRepository.deleteById(id);
    }

    @PutMapping(path = "{id}")
    public void updateAuthorById(@PathVariable("id") int id, @NotNull @RequestBody Book book) {
        Author author = authorRepository.findById(id)
                .orElse(null);
    }

    @PutMapping(path = "{id}/book/{bookId}")
    public void relateAuthorBook(@PathVariable("id") int id, @PathVariable("bookId") int bookId) {
        Author author = authorRepository.findById(id)
                .orElse(null);

        Book book = bookRepository.findById(bookId)
                .orElse(null);

        BookAuthor bookAuthor = new BookAuthor(book, author);
        bookAuthorRepository.save(bookAuthor);

        author.getBooks().add(bookAuthor);
    }
}
