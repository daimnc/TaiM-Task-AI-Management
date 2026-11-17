"""In-memory stand-ins for Firestore and Firebase token verification. Used only by the tests (no network).

Supports what the backend (and the later migration) needs: documents, collections, `where(field, "==", value)`
chains, `limit`, `create` (fails if the document exists), write batches with Firestore's 500-write limit,
`list_documents` (which also returns "phantom" parents that only exist because they have subcollections, like real
Firestore), and a `writes` log so tests can prove that certain paths were never written.
"""
import copy
import itertools

MAX_BATCH_WRITES = 500


class FakeAlreadyExists(Exception):
    """Stands in for google.api_core.exceptions.AlreadyExists."""


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, db, path):
        self._db, self._path = db, path
        self.id = path[-1]
        self.path = "/".join(path)

    def get(self):
        self._db.check_allowed(self._path)
        return FakeSnapshot(self.id, self._db.store.get(self._path))

    def set(self, data):
        self._db.check_allowed(self._path)
        self._db.writes.append(("set", self._path))
        self._db.store[self._path] = copy.deepcopy(data)

    def create(self, data):
        self._db.check_allowed(self._path)
        if self._path in self._db.store:
            raise FakeAlreadyExists(self.path)
        self._db.writes.append(("create", self._path))
        self._db.store[self._path] = copy.deepcopy(data)

    def delete(self):
        self._db.check_allowed(self._path)
        self._db.writes.append(("delete", self._path))
        self._db.store.pop(self._path, None)

    def collection(self, name):
        return FakeCollection(self._db, self._path + (name,))


class FakeQuery:
    def __init__(self, db, path, filters=(), max_results=None):
        self._db, self._path, self._filters, self._limit = db, path, tuple(filters), max_results

    def where(self, field, op, value):
        if op != "==":
            raise NotImplementedError("the fake Firestore only supports == filters")
        return FakeQuery(self._db, self._path, self._filters + ((field, value),), self._limit)

    def limit(self, count):
        return FakeQuery(self._db, self._path, self._filters, count)

    def stream(self):
        self._db.check_allowed(self._path)
        size = len(self._path) + 1
        found = 0
        for path, data in list(self._db.store.items()):
            if len(path) != size or path[:-1] != self._path:
                continue
            if all(data.get(field) == value for field, value in self._filters):
                yield FakeSnapshot(path[-1], data)
                found += 1
                if self._limit is not None and found >= self._limit:
                    return


class FakeCollection(FakeQuery):
    def __init__(self, db, path):
        super().__init__(db, path)

    def document(self, doc_id=None):
        doc_id = doc_id or f"auto{next(self._db.counter):04d}"
        return FakeDocument(self._db, self._path + (doc_id,))

    def list_documents(self):
        """References for every document id under this collection, including parents that have no data of their own."""
        self._db.check_allowed(self._path)
        size = len(self._path) + 1
        seen = []
        for path in list(self._db.store):
            if len(path) >= size and path[:len(self._path)] == self._path and path[size - 1] not in seen:
                seen.append(path[size - 1])
        return [FakeDocument(self._db, self._path + (doc_id,)) for doc_id in seen]


class FakeBatch:
    """All-or-nothing, like Firestore. More than 500 writes fails, and so does `create` on an existing document."""

    def __init__(self, db):
        self._db, self._ops = db, []

    def set(self, ref, data):
        self._ops.append(("set", ref, data))

    def create(self, ref, data):
        self._ops.append(("create", ref, data))

    def delete(self, ref):
        self._ops.append(("delete", ref, None))

    def commit(self):
        if len(self._ops) > MAX_BATCH_WRITES:
            raise ValueError(f"a batch can hold at most {MAX_BATCH_WRITES} writes (got {len(self._ops)})")
        planned = set()
        for op, ref, _data in self._ops:
            if op == "create" and (ref._path in self._db.store or ref._path in planned):
                raise FakeAlreadyExists(ref.path)
            planned.add(ref._path)
        for op, ref, data in self._ops:
            getattr(ref, op)(*([] if op == "delete" else [data]))
        self._ops = []


class FakeFirestore:
    def __init__(self):
        self.store = {}
        self.writes = []  # [("set" | "create" | "delete", path_tuple), ...]
        self.forbidden = []  # path prefixes (tuples) that must never be read: any access raises AssertionError
        self.counter = itertools.count(1)

    def check_allowed(self, path):
        for prefix in self.forbidden:
            if path[:len(prefix)] == prefix:
                raise AssertionError("forbidden Firestore access: " + "/".join(path))

    def collection(self, name):
        return FakeCollection(self, (name,))

    def batch(self):
        return FakeBatch(self)


def fake_verifier(token):
    """'token-alice' is a valid token for user 'alice'. Anything else is rejected like an invalid Firebase token."""
    if token.startswith("token-"):
        uid = token[len("token-"):]
        return {"uid": uid, "email": f"{uid}@example.com", "name": uid.capitalize()}
    raise ValueError("invalid token")
