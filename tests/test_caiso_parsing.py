import math

from iso_data.caiso import _extract_js_array


def test_extracts_plain_array():
    html = "var solarCurt = [1.5, 2, 3.25];"
    assert _extract_js_array(html, "solarCurt") == [1.5, 2.0, 3.25]


def test_handles_na_and_empty_values():
    html = 'var windCurt = [10, "NA", , 5];'
    values = _extract_js_array(html, "windCurt")
    assert values[0] == 10.0
    assert math.isnan(values[1])
    assert math.isnan(values[2])
    assert values[3] == 5.0


def test_handles_json_parse_wrapper():
    html = 'totalCurt = JSON.parse(["[1,2,3]"])'
    assert _extract_js_array(html, "totalCurt") == [1.0, 2.0, 3.0]


def test_missing_variable_returns_empty():
    assert _extract_js_array("<html></html>", "nope") == []
