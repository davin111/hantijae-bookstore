package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.model.BookAuthor;
import com.example.hantijaebookstore.model.Category;
import com.example.hantijaebookstore.repository.AuthorRepository;
import com.example.hantijaebookstore.repository.BookAuthorRepository;
import com.example.hantijaebookstore.repository.BookRepository;
import com.example.hantijaebookstore.repository.CategoryRepository;
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
@RequestMapping("api/category/")
@RestController
public class CategoryController {

    private CategoryRepository categoryRepository;

    @PostMapping
    public ResponseEntity addCategory(@Valid @NotNull @RequestBody Category category) {
        categoryRepository.save(category);
        return new ResponseEntity(category, HttpStatus.CREATED);
    }

    @ResponseBody
    @GetMapping
    public List<Category> getAllCategory() {
        return categoryRepository.findAll();
    }

    @ResponseBody
    @GetMapping(path = "{id}")
    public Category getCategoryById(@PathVariable("id") int id) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return category;
    }

    @DeleteMapping(path = "{id}")
    public void deleteCategoryById(@PathVariable("id") int id) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        categoryRepository.delete(category);
    }

    @PutMapping(path = "{id}")
    public ResponseEntity updateCategoryById(@PathVariable("id") int id, @NotNull @RequestBody Category newCategory) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        category.setName(newCategory.getName());
        return new ResponseEntity(category, HttpStatus.OK);
    }
}
