package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.User;
import com.example.hantijaebookstore.repository.UserRepository;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@AllArgsConstructor
@RequestMapping("api/user/")
@RestController
public class UserController {

    private UserRepository userRepository;

    //@Autowired
    //public BookController(BookRepository bookRepository) {
    //    this.bookRepository = bookRepository;
    //}
//
    @PostMapping
    public ResponseEntity addUser(@Valid @NotNull @RequestBody User user) {
        userRepository.save(user);
        return new ResponseEntity(user, HttpStatus.CREATED);
    }

    @GetMapping
    public List<User> getAllUser() {
        return userRepository.findAll();
    }

//    @GetMapping(path = "{id}")
//    public Book getBookById(@PathVariable("id") int id) {
//        return bookService.getBookById(id)
//                .orElse(null);
//    }
//
//    @DeleteMapping(path = "{id}")
//    public void deleteBookById(@PathVariable("id") int id) {
//        bookService.deleteBook(id);
//    }
//
//    @PutMapping(path = "{id}")
//    public void updateBookById(@PathVariable("id") int id, @Valid @NotNull @RequestBody Book bookToUpdate) {
//        bookService.updateBook(id, bookToUpdate);
//    }
}