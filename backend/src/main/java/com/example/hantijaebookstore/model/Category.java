package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import javax.persistence.*;
import javax.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.List;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class Category extends BaseTimeEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @NotBlank
    @Column(length = 300, nullable = false)
    private String name;

    @Column(length = 100, nullable = false)
    private String type = "normal";

    @OneToMany(mappedBy = "category")
    @JsonIgnore
    private List<BookCategory> bookCategories = new ArrayList<>();
}
