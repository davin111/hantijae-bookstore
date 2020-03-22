package com.example.hantijaebookstore.repository;

import com.example.hantijaebookstore.model.Book;
import org.junit.After;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.junit4.SpringRunner;

import static org.hamcrest.CoreMatchers.is;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThat;

import java.time.LocalDate;
import java.util.List;

@RunWith(SpringRunner.class)
@SpringBootTest
public class BookRepositoryTests {

    @Autowired
    BookRepository bookRepository;

    @After
    public void cleanup() {
        bookRepository.deleteAll();
    }

    @Test
    public void registerBaseTimeEntity() {
        //given
        LocalDate today = LocalDate.now();
        bookRepository.save(Book.builder()
                .title("title")
                .description("description")
                .build());

        //when
        List<Book> bookList = bookRepository.findAll();

        //then
        Book book = bookList.get(0);
        assertEquals(today, book.getCreatedAt().toLocalDate());
        assertEquals(today, book.getUpdatedAt().toLocalDate());
    }

    @Test
    public void saveAndGetBooks() {
        //given
        bookRepository.save(Book.builder()
                .title("test title")
                .description("test desc")
                .build());

        //when
        List<Book> bookList = bookRepository.findAll();

        //then
        Book book = bookList.get(0);
        assertThat(book.getTitle(), is("test title"));
        assertThat(book.getDescription(), is("test desc"));
    }
}
