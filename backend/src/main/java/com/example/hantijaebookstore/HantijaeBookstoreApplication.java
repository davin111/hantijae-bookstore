package com.example.hantijaebookstore;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

@EnableJpaAuditing
@SpringBootApplication
public class HantijaeBookstoreApplication {

	public static void main(String[] args) {
		SpringApplication.run(HantijaeBookstoreApplication.class, args);
	}

}
