# immutable_log.py
# Неизменяемый лог (заглушка)

class ImmutableLog:
    def __init__(self):
        self.chain = []

    def add_entry(self, entry):
        # Простейшая цепочка (можно расширить с хешами позже)
        self.chain.append(entry)

    def get_chain(self):
        return self.chain