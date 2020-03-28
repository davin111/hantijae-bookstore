package com.example.hantijaebookstore.model;

import com.example.hantijaebookstore.repository.BookAuthorRepository;
import com.fasterxml.jackson.annotation.*;
import lombok.*;

import javax.persistence.*;
import javax.validation.constraints.Email;
import javax.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.List;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class Author extends BaseTimeEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @NotBlank
    @Column(length = 100, nullable = false)
    private String familyName;

    @NotBlank
    @Column(length = 100, nullable = false)
    private String givenName;

    @Email
    private String email;

    private String address;

    private String phoneNumber;

    @OneToMany(mappedBy = "author")
    @JsonIgnore
    private List<BookAuthor> bookAuthors = new ArrayList<>();

    @Builder
    public Author(Integer id, @NotBlank String familyName, @NotBlank String givenName, @Email String email, String address, String phoneNumber, List<BookAuthor> bookAuthors) {
        this.id = id;
        this.familyName = familyName;
        this.givenName = givenName;
        this.email = email;
        this.address = address;
        this.phoneNumber = phoneNumber;
        this.bookAuthors = bookAuthors;
    }
}
