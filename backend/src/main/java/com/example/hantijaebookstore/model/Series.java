package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.*;

import javax.persistence.*;
import javax.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.List;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class Series {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @NotBlank
    @Column(length = 500, nullable = false)
    private String name;

    @OneToMany(mappedBy = "series")
    @JsonIgnore
    private List<Book> books = new ArrayList<>();

    @Builder
    public Series(Integer id, @NotBlank String name, List<Book> books) {
        this.id = id;
        this.name = name;
        this.books = books;
    }
}
