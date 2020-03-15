package com.example.hantijaebookstore.model;

import com.fasterxml.jackson.annotation.JsonProperty;

import javax.validation.constraints.NotBlank;
import java.util.UUID;

public class User {
    private final UUID id;

    @NotBlank
    private final String email;

    public User(@JsonProperty("id") UUID id,
                @JsonProperty("email") String email) {
        this.id = id;
        this.email = email;
    }

    public UUID getId() {
        return id;
    }

    public String getEmail() {
        return email;
    }
}
