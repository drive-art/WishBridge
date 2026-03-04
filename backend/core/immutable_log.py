import hashlib
import json
import os
from datetime import datetime

LOG_FILE = os.path.expanduser("~/WishBridge/backend/core/chain.json")

class ImmutableLog:
    def __init__(self):
        self.chain = []
        self.load()

    def hash_entry(self, entry):
        return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()

    def add_entry(self, data):
        previous_hash = self.chain[-1]["hash"] if self.chain else "0"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "data": data,
            "prev_hash": previous_hash
        }
        entry["hash"] = self.hash_entry(entry)
        self.chain.append(entry)
        self.save()

    def save(self):
        with open(LOG_FILE, "w") as f:
            json.dump(self.chain, f, indent=2)

    def load(self):
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                self.chain = json.load(f)
