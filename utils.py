
import uuid
from datetime import datetime

def gen_token():
    return uuid.uuid4().hex

def now_iso():
    return datetime.utcnow().isoformat()
