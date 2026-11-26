package vn.datascope;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Spring Boot phục vụ giao diện và đầu ra tổng hợp đã được Python xử lý. */
@SpringBootApplication
@RestController
public class DataScopeApplication {
    public static void main(String[] args) {
        SpringApplication.run(DataScopeApplication.class, args);
    }

    @GetMapping(value = "/api/dashboard", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Resource> dashboard() {
        return ResponseEntity.ok().cacheControl(CacheControl.noCache())
                .body(new ClassPathResource("static/dashboard.json"));
    }

    @GetMapping(value = "/api/health", produces = MediaType.APPLICATION_JSON_VALUE)
    public String health() {
        return "{\"status\":\"UP\",\"application\":\"Analytix\"}";
    }
}
