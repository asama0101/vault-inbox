from __future__ import annotations

import pytest
from conftest import write  # noqa: F401  (puts scripts/ on sys.path)
from vault_inbox.frontmatter import (
    has_foreign_keys,
    is_ours,
    render,
    set_managed,
    strip_managed,
)

PROPS = {
    "要約": "要約の文",
    "日付": "2026-01-01",
    "関連": ["[[p/x.md|related → x.md]]"],
}

# texts that carry none of our keys: set_managed then strip_managed must give them back
PLAIN = {
    "no frontmatter": "本文\n",
    "empty file": "",
    "no trailing newline": "本文",
    "own frontmatter": "---\ntitle: 題\ntags: [x, y]\n---\n本文\n",
    "crlf": "---\r\ntitle: 題\r\n---\r\n本文\r\n",
    "crlf without frontmatter": "本文\r\n二行目\r\n",
    "bom": "﻿---\ntitle: 題\n---\n本文\n",
    "bom without frontmatter": "﻿本文\n",
    "horizontal rule first": "---\n本文だけ\n",
    "rule and prose between rules": "---\nTitle\n---\n本文\n",
    "empty frontmatter": "---\n---\n本文\n",
    "closing rule at end": "---\ntitle: 題\n---",
    "key that only looks like ours": "---\n要約メモ: 別のキー\n---\n本文\n",
}


@pytest.mark.parametrize("name", PLAIN)
def test_set_then_strip_gives_the_original_back(name):
    text = PLAIN[name]
    assert strip_managed(set_managed(text, PROPS)) == text


@pytest.mark.parametrize("name", PLAIN)
def test_a_text_without_our_keys_is_not_changed_by_strip(name):
    assert strip_managed(PLAIN[name]) == PLAIN[name]


@pytest.mark.parametrize("name", PLAIN)
def test_setting_twice_equals_setting_once(name):
    once = set_managed(PLAIN[name], PROPS)
    assert set_managed(once, PROPS) == once


def test_other_keys_and_the_body_are_kept_byte_for_byte():
    text = "---\ntitle: 題\n# コメント\ntags: [x]\n---\n本文\n- 箇条書き\n"
    out = set_managed(text, PROPS)
    assert out.startswith("---\ntitle: 題\n# コメント\ntags: [x]\n要約:")
    assert out.endswith("---\n本文\n- 箇条書き\n")


def test_old_values_of_our_keys_are_replaced_with_their_list_items():
    text = (
        "---\n関連:\n"
        '  - "[[old]]"\n'
        "- 旧\n要約: 旧\ntitle: 題\nvault-inbox: true\n---\n本文\n"
    )
    out = set_managed(text, {"要約": "新"})
    assert out == '---\ntitle: 題\n要約: "新"\nvault-inbox: true\n---\n本文\n'


def test_a_block_that_only_we_made_goes_away_when_we_remove_everything():
    assert set_managed("本文\n", {}) == "本文\n"
    assert strip_managed(set_managed("本文\n", PROPS)) == "本文\n"


def test_line_endings_follow_the_file():
    out = set_managed("---\r\ntitle: 題\r\n---\r\n本文\r\n", PROPS)
    assert "\n" not in out.replace("\r\n", "")


def test_values_are_written_as_valid_quoted_yaml():
    out = render({"要約": 'a "quoted": #hash\\ and 日本語', "日付": "not a date"})
    assert out == '要約: "a \\"quoted\\": #hash\\\\ and 日本語"\n日付: "not a date"\n'


def test_a_date_is_written_plain_so_obsidian_reads_it_as_a_date():
    assert render({"日付": "2026-01-01"}) == "日付: 2026-01-01\n"


def test_empty_values_are_left_out():
    assert render({"要約": "", "日付": "", "関連": []}) == ""


def test_a_block_with_a_multiline_flow_value_is_still_frontmatter():
    text = "---\ncssclasses: [\n  wide,\n  x\n]\ntitle: 題\n---\n本文\n"
    out = set_managed(text, {"要約": "s"})
    assert out.startswith("---\ncssclasses: [\n  wide,\n  x\n]\ntitle: 題\n要約:")
    assert out.count("---\n") == 2  # no second block was made


@pytest.mark.parametrize(
    "body", ["---\n- item\n- item\n---\n本文\n", "---\nTitle\n---\n本文\n"]
)
def test_a_rule_around_a_list_or_prose_is_not_frontmatter(body):
    out = set_managed(body, {"要約": "s"})
    assert out.endswith(body)  # our block is new, in front of the person's text
    assert strip_managed(out) == body


def test_our_keys_are_ours_only_with_the_marker():
    plain = "---\n日付: 2020-01-01\n---\n本文\n"
    assert has_foreign_keys(plain)
    assert strip_managed(plain) == plain  # the author's keys count as content
    mine = set_managed("本文\n", {"日付": "2026-01-01"})
    assert is_ours(mine)
    assert not has_foreign_keys(mine)


def test_a_block_scalar_with_a_blank_line_is_dropped_whole():
    text = "---\n要約: |\n  a\n\n  b\ntitle: t\nvault-inbox: true\n---\n本文\n"
    assert set_managed(text, {}) == "---\ntitle: t\n---\n本文\n"


def test_a_blank_line_after_our_key_but_before_another_key_stays():
    text = "---\n要約: x\n\ntitle: t\nvault-inbox: true\n---\n本文\n"
    assert strip_managed(text) == "---\n\ntitle: t\n---\n本文\n"


def test_line_separator_characters_are_escaped_in_values():
    ls, ps, nel = chr(0x2028), chr(0x2029), chr(0x85)
    out = render({"関連": [f"a{ls}b", f"c{ps}d", f"e{nel}f"]})
    assert not any(ch in out for ch in (ls, ps, nel))


def test_only_a_real_date_is_written_as_a_date():
    assert render({"日付": "2026-13-45"}) == '日付: "2026-13-45"\n'


OLD_BLOCK = (
    '---\ntitle: 題\n要約: "a"\n日付: 2026-01-01\nタグ:\n  - "x"\n  - "y"\n'
    '関連:\n  - "[[p|r]]"\nvault-inbox: true\n---\n本文\n'
)


def test_the_tag_key_of_an_earlier_version_is_removed_with_our_block():
    assert strip_managed(OLD_BLOCK) == "---\ntitle: 題\n---\n本文\n"
    out = set_managed(OLD_BLOCK, {"要約": "新"})
    assert "タグ" not in out
    assert out == '---\ntitle: 題\n要約: "新"\nvault-inbox: true\n---\n本文\n'


def test_a_persons_own_tag_key_without_our_marker_is_left_alone():
    plain = "---\nタグ: [mine]\n---\n本文\n"
    assert strip_managed(plain) == plain
    assert not has_foreign_keys(plain)  # not one of ours: the file can be marked
    assert "タグ: [mine]" in set_managed(plain, {"要約": "s"})
