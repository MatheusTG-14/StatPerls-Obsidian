from src.enrich.suggest import minimal_view, parse_answers

REC = {"id": "a1", "title": "Dyspareunia", "sections": [
    {"title": "Continuing Education Activity", "blocks": [{"t": "p", "c": [{"t": "text", "v": "CE summary."}]}]},
    {"title": "Introduction", "blocks": [{"t": "p", "c": [{"t": "text", "v": "Painful intercourse. " * 200}]}]},
    {"title": "Etiology", "blocks": [{"t": "p", "c": [{"t": "text", "v": "Secret body text."}]}]},
]}


def test_minimal_view_sends_only_title_headings_intro():
    v = minimal_view(REC, max_chars=100)
    assert v["id"] == "a1" and v["title"] == "Dyspareunia"
    assert v["headings"] == ["Introduction", "Etiology"]
    assert v["intro"].startswith("Painful intercourse.") and len(v["intro"]) <= 100
    assert "Secret" not in str(v) and "CE summary" not in str(v)


def test_parse_answers_validates_ids_and_vocabulary():
    text = "\n".join([
        '{"id": "a1", "category": "obgyn", "confidence": "high"}',
        '{"id": "a2", "category": "cardiology", "confidence": "high"}',
        '{"id": "zz", "category": "skin", "confidence": "low"}',
        'not json',
        '{"id": "a3", "category": "general", "confidence": "medium"}',
    ])
    ok, errors = parse_answers(text, {"a1", "a2", "a3"})
    assert ok == {"a1": ("obgyn", "high"), "a3": ("general", "medium")}
    assert len(errors) == 3


def test_parse_answers_with_subcategory_vocabulary():
    ok, errors = parse_answers('{"id": "a1", "category": "sleep", "confidence": "low"}\n'
                               '{"id": "a2", "category": "skin", "confidence": "high"}', {"a1", "a2"}, {"sleep", "other-nervous-system"})
    assert ok == {"a1": ("sleep", "low")} and len(errors) == 1
