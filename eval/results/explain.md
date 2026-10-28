# Query plans

## no filter, index (ORDER BY distance)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | SIMPLE | c | index | embedding | 10 |  |
| 1 | SIMPLE | a | eq_ref | PRIMARY | 1 |  |

## no filter, exact (ORDER BY distance + 0)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | SIMPLE | c | ALL | None | 4163 | Using filesort |
| 1 | SIMPLE | a | eq_ref | PRIMARY | 1 |  |

## article_length >= 50000, index (ORDER BY distance)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | SIMPLE | a | range | idx_articles_article_length | 115 | Using index condition; Using temporary; Using filesort |
| 1 | SIMPLE | c | ref | uq_chunks_position | 15 |  |

## article_length >= 50000, exact (ORDER BY distance + 0)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | SIMPLE | a | range | idx_articles_article_length | 115 | Using index condition; Using temporary; Using filesort |
| 1 | SIMPLE | c | ref | uq_chunks_position | 15 |  |

## category filter, index (ORDER BY distance)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | PRIMARY | ac | ref | idx_article_categories_category | 28 | Using where; Using index; Using temporary; Using filesort |
| 1 | PRIMARY | a | eq_ref | PRIMARY | 1 |  |
| 1 | PRIMARY | c | ref | uq_chunks_position | 15 |  |

## category filter, exact (ORDER BY distance + 0)

| id | select_type | table | type | key | rows | Extra |
|---|---|---|---|---|---|---|
| 1 | PRIMARY | ac | ref | idx_article_categories_category | 28 | Using where; Using index; Using temporary; Using filesort |
| 1 | PRIMARY | a | eq_ref | PRIMARY | 1 |  |
| 1 | PRIMARY | c | ref | uq_chunks_position | 15 |  |
