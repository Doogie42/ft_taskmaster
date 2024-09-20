import queue


class MyQueue():
    def __init__(self) -> None:
        self.q = queue.Queue()

    def get(self, timeout=None):
        return self.q.get(timeout=timeout)
    
    def put(self, item):
        self.q.put(item)


MyQueue = MyQueue()