import secrets

# Omit easily confused characters: 0/O, 1/I/l.
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"
DEFAULT_CODE_LENGTH = 7


def generate_short_code(length: int = DEFAULT_CODE_LENGTH) -> str:
    if length < 1 or length > 16:
        raise ValueError("Short-code length must be between 1 and 16.")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
