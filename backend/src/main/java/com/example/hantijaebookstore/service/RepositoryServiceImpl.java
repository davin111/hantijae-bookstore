package com.example.hantijaebookstore.service;

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

    public RepositoryServiceImpl() {
        
    }
}
