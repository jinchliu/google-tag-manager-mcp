from google_tag_manager_mcp import render


def test_cell_escapes_and_formats_values():
    assert render.cell('a|b\nc') == 'a\\|b c'
    assert render.cell(True) == 'true'
    assert render.cell(None) == ''
    assert render.cell(['1', '2']) == '1, 2'
    assert render.cell({'a': 1}) == '{"a":1}'


def test_table_and_empty_table():
    assert render.table([], ['a']) == '(none)'
    text = render.table([{'a': 1, 'b': 'x|y'}], ['a', 'b'])
    assert text.splitlines() == ['| a | b |', '|---|---|', '| 1 | x\\|y |']


def test_collection_mentions_count_and_continuation():
    text = render.collection('tags', [{'a': 1}] * 3, ['a'], next_page_token='tok')
    assert text.startswith('tags: 3 items')
    assert "page_token='tok'" in text
    assert 'page_token' not in render.collection('tags', [], ['a'])


def test_json_result_has_structured_content_and_text():
    result = render.json_result({'a': '中'})
    assert result.structured_content == {'a': '中'}
    assert result.content[0].text == '{\n  "a": "中"\n}'


def test_markdown_result_is_text_only():
    result = render.markdown_result('| a |')
    assert result.structured_content is None
    assert result.content[0].text == '| a |'


def test_result_dispatches_on_format():
    calls = []

    def slim():
        calls.append('slim')
        return {'slim': True}

    full = {'full': True}
    assert (
        render.result(
            'json_full', full=full, slim=slim, markdown=str
        ).structured_content
        == full
    )
    assert calls == []
    assert render.result(
        'json', full=full, slim=slim, markdown=str
    ).structured_content == {'slim': True}
    text = render.result('markdown', full=full, slim=slim, markdown=lambda s: f'md:{s}')
    assert text.content[0].text == "md:{'slim': True}"
    assert text.structured_content is None
