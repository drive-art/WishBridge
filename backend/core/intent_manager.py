# intent_manager.py
# Менеджер намерений (шаблон)

class IntentManager:
    def __init__(self):
        self.intents = []

    def add_intent(self, intent):
        self.intents.append(intent)

    def list_intents(self):
        return self.intents