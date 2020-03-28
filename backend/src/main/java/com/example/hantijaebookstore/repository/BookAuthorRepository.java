package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.BookAuthor;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BookAuthorRepository extends JpaRepository<BookAuthor, Integer> {
}
