from proxy_pipeline.parsing import parse_json, parse_text


def test_text_parser_deduplicates_and_validates():
    data = """
    1.1.1.1:80
    http://1.1.1.1:80
    socks5://8.8.8.8:1080
    999.1.1.1:80
    8.8.8.8:70000
    """
    result = parse_text(data, "sample", "http", [])
    assert set(result) == {"1.1.1.1:80", "8.8.8.8:1080"}
    assert result["1.1.1.1:80"].protocols == {"http"}
    assert result["8.8.8.8:1080"].protocols == {"socks5"}


def test_json_parser_reads_metadata():
    data = """
    {
      "data": [
        {"ip": "1.1.1.1", "port": 8080, "protocol": "https", "country_code": "AU", "anonymity": "elite"},
        {"proxy": "socks4://8.8.8.8:1080"}
      ]
    }
    """
    result = parse_json(data, "sample", "auto", ["http"])
    assert result["1.1.1.1:8080"].protocols == {"https"}
    assert result["1.1.1.1:8080"].reported_country == "AU"
    assert result["1.1.1.1:8080"].reported_anonymity == "elite"
    assert result["8.8.8.8:1080"].protocols == {"socks4"}
