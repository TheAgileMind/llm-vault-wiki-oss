from llm_vault_wiki.frontmatter import derive_title, parse_frontmatter


def test_parse_frontmatter_and_derive_title():
    text = "---\ntitle: Real Title\ntype: domain-note\nstatus: active\n---\n# Heading\nBody"

    result = parse_frontmatter(text)

    assert result.data["title"] == "Real Title"
    assert result.body.startswith("# Heading")
    assert derive_title("fallback", result.data, result.body) == "Real Title"


def test_invalid_frontmatter_returns_body_and_error():
    result = parse_frontmatter("---\ntitle: [broken\n---\nBody")

    assert result.error
    assert "Body" in result.body
