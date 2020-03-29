package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.repository.BookRepository;
import com.example.hantijaebookstore.service.BookService;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.persistence.EntityNotFoundException;
import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@AllArgsConstructor
@RequestMapping("api/book/")
@RestController
public class BookController {

    private BookRepository bookRepository;

    private BookService bookService;

    @PostMapping
    public ResponseEntity addBook(@Valid @NotNull @RequestBody Book book) {
        bookRepository.save(book);
        return new ResponseEntity(book, HttpStatus.CREATED);
    }

    @ResponseBody
    @GetMapping
    public List<Map> getAllBook() {
        return bookService.serializeBooks(bookRepository.findAll());
    }

    @ResponseBody
    @GetMapping(path = "{id}")
    public Map getBookById(@PathVariable("id") int id) {
        Book book = bookRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return bookService.serializeBook(book);
    }

    @DeleteMapping(path = "{id}")
    public void deleteBookById(@PathVariable("id") int id) {
        Book book = bookRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        bookRepository.delete(book);
    }

    @PutMapping(path = "{id}")
    public ResponseEntity updateBookById(@PathVariable("id") int id, @Valid @NotNull @RequestBody Book newBook) {
        Book book = bookRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        book.setTitle(newBook.getTitle());
        book.setSubtitle(newBook.getSubtitle());
        book.setShortDescription(newBook.getShortDescription());
        book.setDescription(newBook.getDescription());
        book.setFullPrice(newBook.getFullPrice());
        book.setPrice(newBook.getPrice());
        book.setISBN(newBook.getISBN());
        book.setPageCount(newBook.getPageCount());
        book.setSize(newBook.getSize());
        book.setExtraURL(newBook.getExtraURL());
        book.setEbookURL(newBook.getEbookURL());
        return new ResponseEntity(book, HttpStatus.OK);
    }
}