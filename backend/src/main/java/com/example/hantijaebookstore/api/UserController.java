package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.User;
import com.example.hantijaebookstore.repository.UserRepository;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@AllArgsConstructor
@RequestMapping("api/user/")
@RestController
public class UserController {

    private UserRepository userRepository;

    @PostMapping
    public ResponseEntity addUser(@Valid @NotNull @RequestBody User user) {
        userRepository.save(user);
        return new ResponseEntity(user, HttpStatus.CREATED);
    }

    @GetMapping
    public List<User> getAllUser() {
        return userRepository.findAll();
    }

    @GetMapping(path = "{id}")
    public User getUserById(@PathVariable("id") int id) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return user;
    }

    @DeleteMapping(path = "{id}")
    public void deleteUserById(@PathVariable("id") int id) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        userRepository.delete(user);
    }

    @PutMapping(path = "{id}")
    public ResponseEntity updateUserById(@PathVariable("id") int id, @Valid @NotNull @RequestBody User newUser) {
        User user = userRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        user.setEmail(newUser.getEmail());
        user.setAddress(newUser.getAddress());
        user.setPhoneNumber(newUser.getPhoneNumber());
        return new ResponseEntity(user, HttpStatus.OK);
    }
}