"""Session undo commands; authoritative values remain with their owners."""
class History:
    def __init__(self):
        self._undo = []
        self._redo = []
        self.replaying = False
        self.result = None

    def record(self, undo, redo, label):
        if not self.replaying:
            self._undo.append((undo,redo,label))
            self._redo.clear()

    def undo(self, redo=False):
        source,target = (self._redo,self._undo) if redo else (self._undo,self._redo)
        if not source:
            return None
        command = source[-1]
        self.replaying = True
        try:
            self.result = command[1 if redo else 0]()
            source.pop()
            target.append(command)
            return command[2]
        finally:
            self.replaying = False
