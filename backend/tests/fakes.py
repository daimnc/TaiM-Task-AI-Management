"""In-memory stand-ins for Firestore and Firebase token verification. Used only by the tests (no network)."""
import copy
import itertools


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, store, path, counter):
        self._store, self._path, self._counter = store, path, counter
        self.id = path[-1]

    def get(self):
        return FakeSnapshot(self.id, self._store.get(self._path))

    def set(self, data):
        self._store[self._path] = copy.deepcopy(data)

    def delete(self):
        self._store.pop(self._path, None)

    def collection(self, name):
        return FakeCollection(self._store, self._path + (name,), self._counter)


class FakeCollection:
    def __init__(self, store, path, counter):
        self._store, self._path, self._counter = store, path, counter

    def document(self, doc_id=None):
        doc_id = doc_id or f"auto{next(self._counter):04d}"
        return FakeDocument(self._store, self._path + (doc_id,), self._counter)

    def stream(self):
        size = len(self._path) + 1
        for path, data in list(self._store.items()):
            if len(path) == size and path[:-1] == self._path:
                yield FakeSnapshot(path[-1], data)


class FakeFirestore:
    def __init__(self):
        self.store = {}
        self._counter = itertools.count(1)

    def collection(self, name):
        return FakeCollection(self.store, (name,), self._counter)


def fake_verifier(token):
    """'token-alice' is a valid token for user 'alice'. Anything else is rejected like an invalid Firebase token."""
    if token.startswith("token-"):
        uid = token[len("token-"):]
        return {"uid": uid, "email": f"{uid}@example.com", "name": uid.capitalize()}
    raise ValueError("invalid token")
