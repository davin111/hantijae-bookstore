package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.Category;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CategoryRepository extends JpaRepository<Category, Integer> {
}
