"""Reading the vector index definition back from SHOW CREATE TABLE."""

import pytest

from src.database.repositories.articles import vector_index_definition

CREATE = """CREATE TABLE `article_chunks` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `embedding` vector(768) NOT NULL,
  PRIMARY KEY (`id`),
  VECTOR KEY `embedding` (`embedding`) {options},
  CONSTRAINT `fk_chunks_article` FOREIGN KEY (`article_id`) REFERENCES `articles` (`id`)
) ENGINE=InnoDB"""


@pytest.mark.parametrize(
    "options",
    ["`M`=16 `DISTANCE`=cosine", "`M`='16' `DISTANCE`='cosine'", "M=16 DISTANCE=cosine"],
)
def test_reads_m_and_distance(options: str) -> None:
    assert vector_index_definition(CREATE.format(options=options)) == ("embedding", 16, "cosine")


def test_defaults_are_left_out() -> None:
    create = CREATE.replace(" {options}", "")

    assert vector_index_definition(create) == ("embedding", None, None)


def test_missing_index_is_an_error() -> None:
    with pytest.raises(ValueError, match="no vector index"):
        vector_index_definition("CREATE TABLE `article_chunks` (`id` int(11))")


def test_unexpected_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="unexpected distance"):
        vector_index_definition(CREATE.format(options="`M`=16 `DISTANCE`=manhattan"))
