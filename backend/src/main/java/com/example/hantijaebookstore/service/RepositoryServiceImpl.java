package com.example.hantijaebookstore.service;

import com.example.hantijaebookstore.repository.AuthorRepository;
import com.example.hantijaebookstore.repository.BookAuthorRepository;
import com.example.hantijaebookstore.repository.BookRepository;
import com.example.hantijaebookstore.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class RepositoryServiceImpl implements RepositoryService {
    @Autowired
    private UserRepository userRepository;

    @Autowired
    private BookRepository bookRepository;

    @Autowired
    private AuthorRepository authorRepository;

    @Autowired
    private BookAuthorRepository bookAuthorRepository;

    public RepositoryServiceImpl() {

    }
}
