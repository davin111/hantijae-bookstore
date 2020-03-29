package com.example.hantijaebookstore.dto;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Book;
import com.example.hantijaebookstore.model.BookAuthor;
import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.*;
import org.hibernate.validator.constraints.URL;

import javax.persistence.Column;
import javax.persistence.OneToMany;
import javax.validation.constraints.Min;
import java.util.ArrayList;
import java.util.List;

@NoArgsConstructor
@Getter
@Setter
public class GetBooksByCategoryDto {
    private Integer id;
    private String title;
    private String subtitle;
    private String shortDescription;
    private String description;
    private Integer fullPrice;
    private Integer price;
    private String ISBN;
    private Integer pageCount;
    private String size;
    private String extraURL;
    private String ebookURL;
    private List<Author> authors = new ArrayList<>();
}
