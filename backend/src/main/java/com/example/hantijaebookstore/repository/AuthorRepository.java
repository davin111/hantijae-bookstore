package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.Author;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AuthorRepository extends JpaRepository<Author, Integer> {
}
