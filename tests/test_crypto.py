from app.auth.crypto import encrypt_token, decrypt_token


def test_encrypt_decrypt_roundtrip():
    original = "ya29.access_token_value"
    encrypted = encrypt_token(original)
    assert encrypted != original
    assert decrypt_token(encrypted) == original


def test_different_encryptions_same_plaintext():
    t1 = encrypt_token("secret")
    t2 = encrypt_token("secret")
    assert t1 != t2
