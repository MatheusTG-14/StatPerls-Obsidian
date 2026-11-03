from src.migrate.bookmarks import rewrite


def test_rewrite_nested_groups():
    bm = {"items": [
        {"type": "file", "path": "StatPearls/Articles/Potassium.md"},
        {"type": "group", "title": "G", "items": [{"type": "file", "path": "StatPearls/Articles/Milia.md"},
                                                 {"type": "file", "path": "Mine/notes.md"}]},
    ]}
    moves = {"Articles/Potassium.md": "Articles/Endocrine and Metabolism/Potassium.md", "Articles/Milia.md": "Articles/Skin/Milia.md"}
    new, n = rewrite(bm, moves)
    assert n == 2
    assert new["items"][0]["path"] == "StatPearls/Articles/Endocrine and Metabolism/Potassium.md"
    assert new["items"][1]["items"][0]["path"] == "StatPearls/Articles/Skin/Milia.md"
    assert new["items"][1]["items"][1]["path"] == "Mine/notes.md"
    assert bm["items"][0]["path"] == "StatPearls/Articles/Potassium.md"  # input untouched
