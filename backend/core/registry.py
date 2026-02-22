# registry.py
# Реестр агентов (заглушка)

class AgentRegistry:
    def __init__(self):
        self.agents = []

    def register(self, agent):
        self.agents.append(agent)

    def list_agents(self):
        return self.agents