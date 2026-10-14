from .types import RuntimeID


class CommandQueue(list):
    def __init__(self, *items):
        """CommandQueue is responsible for managing a queue of commands."""
        super(CommandQueue, self).__init__(items)

    def add_command(self, command_id: str, caller: RuntimeID, receiver: RuntimeID, data: dict):
        """Add a command to the queue."""
        self.append((command_id, caller, receiver, data))
