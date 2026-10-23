from blog.tags import tag_url


def test_tag_url_slugs_the_name():
    assert tag_url("Machine Learning") == "/tags/machine-learning"
