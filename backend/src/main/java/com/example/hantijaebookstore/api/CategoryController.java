package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.dto.GetBooksByCategoryDto;
import com.example.hantijaebookstore.model.*;
import com.example.hantijaebookstore.repository.*;
import com.example.hantijaebookstore.service.AuthorService;
import com.example.hantijaebookstore.service.BookService;
import com.example.hantijaebookstore.service.CategoryService;
import com.example.hantijaebookstore.util.ObjectMapperUtils;
import lombok.AllArgsConstructor;
import org.modelmapper.ModelMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.*;

@AllArgsConstructor
@RequestMapping("api/category/")
@RestController
public class CategoryController {

    private CategoryRepository categoryRepository;

    private CategoryService categoryService;

    private BookRepository bookRepository;

    private BookService bookService;

    private BookCategoryRepository bookCategoryRepository;

    @Autowired
    private ModelMapper modelMapper;

    @PostMapping
    public ResponseEntity addCategory(@Valid @NotNull @RequestBody Category category) {
        categoryRepository.save(category);
        return new ResponseEntity(category, HttpStatus.CREATED);
    }

    @ResponseBody
    @GetMapping
    public List<Map> getAllCategory() {
        return categoryService.serializeCategories(categoryRepository.findAll());
    }

    @ResponseBody
    @GetMapping(path = "{id}")
    public Map getCategoryById(@PathVariable("id") int id) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return categoryService.serializeCategory(category);
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

    @PutMapping(path = "{id}/book/{bookId}")
    public void relateCategoryWithBook(@PathVariable("id") int id, @PathVariable("bookId") int bookId) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        Book book = bookRepository.findById(bookId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        BookCategory bookCategory = new BookCategory(book, category);
        bookCategoryRepository.save(bookCategory);

        category.getBookCategories().add(bookCategory);
    }

    @GetMapping(path = "{id}/book/")
    public List<Map> getBooksByCategory(@PathVariable("id") int id) {
        Category category = categoryRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        List<Book> books = new ArrayList<>();
        for (int i = 0; i < category.getBookCategories().size(); i++) {
            books.add(category.getBookCategories().get(i).getBook());
        }

        return bookService.serializeBooks(books);
        //List<GetBooksByCategoryDto> bookDtos = ObjectMapperUtils.mapAll(books, GetBooksByCategoryDto.class);
        //return bookDtos;
    }
}
