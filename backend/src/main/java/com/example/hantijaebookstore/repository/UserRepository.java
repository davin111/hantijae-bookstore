package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.User;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Integer> {
}
