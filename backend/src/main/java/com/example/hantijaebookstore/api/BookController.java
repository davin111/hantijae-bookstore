package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.repository.BookRepository;
import lombok.AllArgsConstructor;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@AllArgsConstructor
@RequestMapping("api/book/")
@RestController
public class BookController {

    private BookRepository bookRepository;

    @PostMapping
    public void addBook(@Valid @NotNull @RequestBody Book book) {
        bookRepository.save(book);
    }

    @GetMapping
    public List<Book> getAllBook() {
        return bookRepository.findAll();
    }

    @GetMapping(path = "{id}")
    public Book getBookById(@PathVariable("id") int id) {
        return bookRepository.findById(id)
                .orElse(null);
    }

    @DeleteMapping(path = "{id}")
    public void deleteBookById(@PathVariable("id") int id) {
        bookRepository.deleteById(id);
    }

//    @PutMapping(path = "{id}")
//    public void updateBookById(@PathVariable("id") int id, @Valid @NotNull @RequestBody Book bookToUpdate) {
//        bookRepository.
//    }
}