package com.example.hantijaebookstore.model;

import lombok.*;

import javax.persistence.*;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class BookCategory {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @ManyToOne
    @JoinColumn(name = "book_id")
    private Book book;

    @ManyToOne
    @JoinColumn(name = "category_id")
    private Category category;

    @Column(length = 100)
    private String type = "normal";

    @Builder
    public BookCategory(Book book, Category category) {
        this.book = book;
        this.category = category;
    }

    @Builder
    public BookCategory(Integer id, Book book, Category category, String type) {
        this.id = id;
        this.book = book;
        this.category = category;
        this.type = type;
    }
}
