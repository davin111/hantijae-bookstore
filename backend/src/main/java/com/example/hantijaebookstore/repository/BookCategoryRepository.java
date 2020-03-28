package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.BookCategory;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BookCategoryRepository extends JpaRepository<BookCategory, Integer> {
}
