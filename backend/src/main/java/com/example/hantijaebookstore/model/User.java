package com.example.hantijaebookstore.model;

import lombok.*;

import javax.persistence.*;
import javax.validation.constraints.Email;
import javax.validation.constraints.NotBlank;

@NoArgsConstructor(access = AccessLevel.PROTECTED)
@Getter
@Setter
@Entity
public class User extends BaseTimeEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @NotBlank
    @Email
    @Column(nullable = false)
    private String email;

    @NotBlank
    @Column(nullable = false)
    private String address;

    @NotBlank
    @Column(nullable = false)
    private String phoneNumber;

    @Builder
    public User(Integer id, @NotBlank @Email String email, String address, String phoneNumber) {
        this.id = id;
        this.email = email;
        this.address = address;
        this.phoneNumber = phoneNumber;
    }
}
