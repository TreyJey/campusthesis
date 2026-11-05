import hashlib

# пока sha, если будет врремя - то на bcrypt перенести
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()