import json
import os
from limits.storage import Storage
from limits.util import parse_many
from datetime import datetime, timedelta
from limits.errors import ConfigurationError

class FileStorage(Storage):
    def __init__(self, uri, **options):
        self.file_path = options.get("file_path", "data/rate_limits/limiter.json")
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self.storage = self._load()

    @property
    def base_exceptions(self):
        return (ConfigurationError,)

    def _load(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.storage, f)

    def get(self, key):
        self.storage = self._load()
        now = datetime.now().timestamp()
        if key in self.storage:
            expiry, count = self.storage[key]
            if now < expiry:
                return count
            else:
                del self.storage[key]
                self._save()
        return 0

    def incr(self, key, expiry, elastic_expiry=False):
        self.storage = self._load()
        now = datetime.now().timestamp()
        
        if key in self.storage:
            exp, count = self.storage[key]
            if now >= exp and not elastic_expiry:
                count = 0
        else:
            count = 0

        count += 1
        self.storage[key] = (now + expiry, count)
        self._save()
        return count

    def check(self):
        return True

    def reset(self):
        self.storage = {}
        self._save()

    def clear(self, key):
        self.storage = self._load()
        if key in self.storage:
            del self.storage[key]
            self._save()

    def get_expiry(self, key):
        self.storage = self._load()
        if key in self.storage:
            expiry, _ = self.storage[key]
            return datetime.fromtimestamp(expiry)
        return datetime.now()

    def get_num_requests(self, key):
        return self.get(key)