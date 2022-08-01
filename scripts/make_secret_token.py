import hashlib
import hmac
import os
import time

name = input('name > ').strip()
secret_key = (os.getenv('SECRET_KEY') or input('secret_key > ')).strip()

token_ttl_str = input('token_ttl (default: 3600) > ').strip()
if not token_ttl_str:
    token_ttl_str = "3600"

token_exp_str = str(int(time.time() + int(token_ttl_str)))

token_digest = hmac.new(
    key=hashlib.sha256(secret_key.encode()).digest(),
    msg=f"{token_exp_str}:{name}".encode(),
    digestmod=hashlib.sha256,
).hexdigest()

print(f"{token_digest}:{token_exp_str}")
