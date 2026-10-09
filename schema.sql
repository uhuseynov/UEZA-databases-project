-- Runs automatically the first time the database starts with an empty data volume.

CREATE TABLE articles (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    page_id        INT UNSIGNED NOT NULL UNIQUE,      -- MediaWiki page id
    title          VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL UNIQUE,
    url            VARCHAR(500),
    article_length INT UNSIGNED NOT NULL,             -- size reported by MediaWiki
    revision_id    BIGINT UNSIGNED NOT NULL,          -- stored revision, compared during sync
    last_edit_date DATETIME NOT NULL,                 -- time of that revision (UTC)
    INDEX idx_articles_article_length (article_length),
    INDEX idx_articles_last_edit_date (last_edit_date)
);

CREATE TABLE article_categories (
    article_id INT NOT NULL,
    category   VARCHAR(255) NOT NULL,
    PRIMARY KEY (article_id, category),
    INDEX idx_article_categories_category (category),
    CONSTRAINT fk_categories_article FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE TABLE article_links (
    article_id   INT NOT NULL,                        -- the article that contains the link
    linked_title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    PRIMARY KEY (article_id, linked_title),
    INDEX idx_article_links_linked_title (linked_title),
    CONSTRAINT fk_links_article FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE TABLE article_chunks (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    article_id  INT NOT NULL,
    chunk_index INT NOT NULL,                         -- position in the article, from 0
    chunk_text  TEXT NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    UNIQUE KEY uq_chunks_position (article_id, chunk_index),
    CONSTRAINT fk_chunks_article FOREIGN KEY (article_id) REFERENCES articles(id),
    VECTOR INDEX (embedding) DISTANCE=cosine
);
