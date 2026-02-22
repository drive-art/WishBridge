# base_agent.py
# Базовый агент

class BaseAgent:
    def __init__(self, name):
        self.name = name

    def act(self, intent):
        print(f"{self.name} processing intent: {intent}")