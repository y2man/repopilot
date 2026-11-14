from app.core.security import hash_password, verify_password, create_token, decode_token

def test_password_hash_is_salted_and_verifiable():
    first = hash_password('correct horse battery staple')
    second = hash_password('correct horse battery staple')
    assert first != second
    assert verify_password('correct horse battery staple', first)
    assert not verify_password('wrong password', first)

def test_token_round_trip():
    token = create_token(42)
    assert decode_token(token) == 42
