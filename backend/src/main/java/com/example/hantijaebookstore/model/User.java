package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.JsonProperty;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.validation.constraints.NotBlank;

@Entity
public class User {
    @Id
    @GeneratedValue(strategy = GenerationType.AUTO)
    private Integer id;

    private String email;

    public User() {

    }

    public User(@JsonProperty("id") Integer id,
                @JsonProperty("email") String email) {
        this.id = id;
        this.email = email;
    }

    public Integer getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }
}
