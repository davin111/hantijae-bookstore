package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.Book;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BookRepository extends JpaRepository<Book, Integer> {
}
