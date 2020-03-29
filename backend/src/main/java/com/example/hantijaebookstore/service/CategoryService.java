package com.example.hantijaebookstore.service;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.model.Category;
import com.example.hantijaebookstore.repository.CategoryRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class CategoryService {
    @Autowired
    private CategoryRepository categoryRepository;

    @Autowired
    private BookService bookService;

    public CategoryService(CategoryRepository categoryRepository) {
        this.categoryRepository = categoryRepository;
    }

    public Map serializeCategory(Category category) {
        Map<String, Object> response = new HashMap<>();
        response.put("id", category.getId());
        response.put("name", category.getName());
        response.put("type", category.getType());

        List<Book> books = new ArrayList<Book>();
        for (int i = 0; i < category.getBookCategories().size(); i++) {
            books.add(category.getBookCategories().get(i).getBook());
        }
        response.put("books", bookService.serializeBooks(books));
        return response;
    }

    public List<Map> serializeCategories(List<Category> categories) {
        List<Map> response = new ArrayList<>();
        for (int i = 0; i < categories.size(); i++) {
            response.add(serializeCategory(categories.get(i)));
        }
        return response;
    }
}
