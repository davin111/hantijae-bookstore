package com.example.hantijaebookstore.model;

import lombok.*;

import javax.persistence.*;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
@Table(uniqueConstraints={
        @UniqueConstraint(columnNames = {"book_id", "author_id"})
})
public class BookAuthor {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @ManyToOne
    @JoinColumn(name = "book_id")
    private Book book;

    @ManyToOne
    @JoinColumn(name = "author_id")
    private Author author;

    @Column(length = 100)
    private String type = "normal";

    @Builder
    public BookAuthor(Book book, Author author) {
        this.book = book;
        this.author = author;
    }
}
