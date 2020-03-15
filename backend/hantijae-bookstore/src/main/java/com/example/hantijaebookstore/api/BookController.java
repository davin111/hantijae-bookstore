package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.service.BookService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@RequestMapping("api/book/")
@RestController
public class BookController {

    private final BookService bookService;

    @Autowired
    public BookController(BookService bookService) {
        this.bookService = bookService;
    }

    @PostMapping
    public void addBook(@Valid @NotNull @RequestBody Book book) {
        bookService.addBook(book);
    }

    @GetMapping
    public List<Book> getAllBook() {
        return bookService.getAllBook();
    }

    @GetMapping(path = "{id}")
    public Book getBookById(@PathVariable("id") int id) {
        return bookService.getBookById(id)
                .orElse(null);
    }

    @DeleteMapping(path = "{id}")
    public void deleteBookById(@PathVariable("id") int id) {
        bookService.deleteBook(id);
    }

    @PutMapping(path = "{id}")
    public void updateBookById(@PathVariable("id") int id, @Valid @NotNull @RequestBody Book bookToUpdate) {
        bookService.updateBook(id, bookToUpdate);
    }
}
