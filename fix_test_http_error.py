with open("tests/test_crawler_download.py") as f:
    content = f.read()

content = content.replace(
    "        mock_response.raise_for_status.side_effect =",
    "        mock_response.is_redirect = False\n        mock_response.raise_for_status.side_effect =",
)

with open("tests/test_crawler_download.py", "w") as f:
    f.write(content)
