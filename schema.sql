-- Runs automatically the first time the database starts with an empty data volume.

CREATE TABLE articles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255),
    category VARCHAR(100),
    url VARCHAR(500),
    edited_at DATE
);

CREATE TABLE article_chunks (
    id INT PRIMARY KEY AUTO_INCREMENT,
    article_id INT,
    chunk_text TEXT,
    embedding VECTOR(768) NOT NULL,
    FOREIGN KEY (article_id) REFERENCES articles(id),
    VECTOR INDEX (embedding) DISTANCE=cosine
);
