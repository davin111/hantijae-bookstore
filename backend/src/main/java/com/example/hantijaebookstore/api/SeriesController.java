package com.example.hantijaebookstore.api;

import com.example.hantijaebookstore.model.Author;
import com.example.hantijaebookstore.model.Series;
import com.example.hantijaebookstore.repository.SeriesRepository;
import lombok.AllArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import javax.validation.Valid;
import javax.validation.constraints.NotNull;
import java.util.List;

@AllArgsConstructor
@RequestMapping("api/series/")
@RestController
public class SeriesController {

    private SeriesRepository seriesRepository;

    @PostMapping
    public ResponseEntity addSeries(@Valid @NotNull @RequestBody Series series) {
        seriesRepository.save(series);
        return new ResponseEntity(series, HttpStatus.CREATED);
    }

    @GetMapping
    public List<Series> getAllSeries() {
        return seriesRepository.findAll();
    }

    @GetMapping(path = "{id}")
    public Series getSeriesById(@PathVariable("id") int id) {
        Series series = seriesRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        return series;
    }

    @DeleteMapping(path = "{id}")
    public void deleteSeriesById(@PathVariable("id") int id) {
        Series series = seriesRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        seriesRepository.delete(series);
    }

    @PutMapping(path = "{id}")
    public ResponseEntity updateSeriesById(@PathVariable("id") int id, @Valid @NotNull @RequestBody Series newSeries) {
        Series series = seriesRepository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));

        series.setName(newSeries.getName());
        return new ResponseEntity(series, HttpStatus.OK);
    }
}