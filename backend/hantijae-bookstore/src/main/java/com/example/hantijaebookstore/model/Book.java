package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.JsonProperty;

import javax.validation.constraints.NotBlank;

public class Book {
    private final int id;
    private final String description;

    @NotBlank
    private final String title;

    public Book(@JsonProperty("id") int id,
                @JsonProperty("title") String title,
                @JsonProperty("description") String description) {
        this.id = id;
        this.title = title;
        this.description = description;
    }

    public int getId() {
        return id;
    }

    public String getTitle() {
        return title;
    }

    public String getDescription() {
        return description;
    }
}
