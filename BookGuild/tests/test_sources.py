from bookguild.research.search import SearchHit
from bookguild.research.sources import (
    SourceRegistry,
    normalise_url,
    remove_excluded_citations,
    score_source,
)


def test_quality_scores():
    assert score_source("https://www.pinterest.com/pin/1")[0] == 0
    assert score_source("https://doi.org/10.1/x", scholarly=True)[0] == 90
    assert score_source("https://www.tifr.res.in/bios.pdf")[0] == 85
    assert score_source("https://history.stanford.edu/x")[0] == 85
    assert score_source("https://www.nobelprize.org/prizes/physics/1930/raman/")[0] == 80
    assert score_source("https://en.wikipedia.org/wiki/C._V._Raman")[0] == 65
    assert score_source("https://someblog.blogspot.com/post")[0] == 25
    assert score_source("https://randomsite.net/page")[0] == 50


def test_registry_numbers_merges_and_blocks():
    registry = SourceRegistry()
    a = registry.add(SearchHit("A", "https://www.nobelprize.org/raman/", "snippet", "duckduckgo"), "Scout-1", "q1")
    same = registry.add(SearchHit("A", "https://nobelprize.org/raman", "full page " * 50, "tavily", full_text=True),
                        "Scout-2", "q2")
    blocked = registry.add(SearchHit("P", "https://pinterest.com/x", "", "duckduckgo"), "Scout-1", "q1")
    b = registry.add(SearchHit("B", "https://en.wikipedia.org/wiki/Raman", "w", "wikipedia"), "Scout-3", "q3")

    assert a is same and a.id == "S1" and b.id == "S2"
    assert a.found_by == ["Scout-1", "Scout-2"] and a.queries == ["q1", "q2"]
    assert a.full_text and a.text.startswith("full page")  # the richer copy wins
    assert blocked is None
    assert normalise_url("https://www.X.org/a/") == normalise_url("http://x.org/a")


def test_excluded_sources_are_removed_from_notes():
    notes = "### Early life\n- Born in 1888 [S1]\n- Studied in Madras [S2][S3]\n- A legend [S3]\n- No cite here"
    cleaned = remove_excluded_citations(notes, {"S3"})
    assert "- Born in 1888 [S1]" in cleaned
    assert "- Studied in Madras [S2]" in cleaned and "[S3]" not in cleaned
    assert "A legend" not in cleaned
    assert "No cite here" in cleaned and "### Early life" in cleaned


def test_same_page_with_different_url_is_merged_and_titles_cleaned():
    registry = SourceRegistry()
    a = registry.add(SearchHit("C. V. Raman", "https://en.wikipedia.org/wiki/C._V._Raman", "x", "wikipedia"),
                     "Scout-1", "q")
    b = registry.add(SearchHit("C. V.  Raman", "https://en.wikipedia.org/wiki/C.V._Raman", "y", "duckduckgo"),
                     "Scout-2", "q")
    c = registry.add(SearchHit("Saha equation\n   \n", "https://kids.britannica.com/saha", "z", "exa"), "Scout-3", "q")
    assert a is not None and a.title == "C. V. Raman"
    assert b is a and a.found_by == ["Scout-1", "Scout-2"]
    assert c.title == "Saha equation"
