from cryptography.fernet import Fernet
from app.config import settings

_fernet = Fernet(settings.fernet_key.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
