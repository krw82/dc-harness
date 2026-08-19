from dc_harness.normalize import author_hash, clean_text, normalize_label


def test_clean_text_strips_tags_and_entities():
    assert clean_text("<p>가격 &amp; 전망</p>\n\n  뿌우  ") == "가격 & 전망 뿌우"


def test_clean_text_removes_dc_noise():
    assert "\u200b" not in clean_text("본문\u200b제로폭")  # 제로폭/비표시 문자 제거
    assert clean_text("<b>제목</b>") == "제목"


def test_author_hash_stable_and_salted():
    a = author_hash("닉네임", "salt1")
    b = author_hash("닉네임", "salt2")
    assert a != b and len(a) == 12


def test_normalize_label_for_dedupe():
    assert normalize_label("  Bitcoin ") == normalize_label("bitcoin")
    assert normalize_label("비트코인") == "비트코인"
