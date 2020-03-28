package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.*;
import lombok.*;
import org.hibernate.validator.constraints.URL;

import javax.persistence.*;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.List;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class Book extends BaseTimeEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @NotBlank
    @Column(length = 500, nullable = false)
    private String title;

    @Column(length = 1000)
    private String subtitle;

    @Column(length = 3000)
    private String shortDescription;

    @Column(columnDefinition = "TEXT")
    private String description;

    @Min(value=0, message = "The value must be positive.")
    @Column(nullable = false)
    private Integer fullPrice;

    @Min(value=0, message = "The value must be positive.")
    private Integer price;

    private String ISBN;

    @Min(value=0, message = "The value must be positive.")
    private Integer pageCount;

    private String size;

    @URL(protocol = "http")
    private String extraURL;

    @URL(protocol = "http")
    private String ebookURL;

    @OneToMany(mappedBy = "book")
    @JsonIgnore
    private List<BookAuthor> bookAuthors = new ArrayList<>();

    @OneToMany(mappedBy = "book")
    @JsonIgnore
    private List<BookCategory> bookCategories = new ArrayList<>();

    @ManyToOne
    private Series series;

    @Builder
    public Book(Integer id, @NotBlank String title, String subtitle, String shortDescription, String description,
                @Min(value = 0, message = "The value must be positive.") Integer fullPrice,
                @Min(value = 0, message = "The value must be positive.") Integer price, String ISBN,
                @Min(value = 0, message = "The value must be positive.") Integer pageCount, String size,
                @URL(protocol = "http") String extraURL, @URL(protocol = "http") String ebookURL,
                List<BookAuthor> bookAuthors, Series series) {
        this.id = id;
        this.title = title;
        this.subtitle = subtitle;
        this.shortDescription = shortDescription;
        this.description = description;
        this.fullPrice = fullPrice;
        this.price = price;
        this.ISBN = ISBN;
        this.pageCount = pageCount;
        this.size = size;
        this.extraURL = extraURL;
        this.ebookURL = ebookURL;
        this.bookAuthors = bookAuthors;
        this.series = series;
    }
}
