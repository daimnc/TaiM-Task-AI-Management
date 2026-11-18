"""In-memory stand-ins for Firestore and Firebase token verification. Used only by the tests (no network).

Supports what the backend (and the later migration) needs: documents, collections, `where(field, "==", value)`
chains, `limit`, `create` (fails if the document exists), write batches with Firestore's 500-write limit,
`list_documents` (which also returns "phantom" parents that only exist because they have subcollections, like real
Firestore), and a `writes` log so tests can prove that certain paths were never written.
"""
import copy
import itertools
import threading

MAX_BATCH_WRITES = 500
MAX_TXN_ATTEMPTS = 5  # same as Firestore's default


class FakeAlreadyExists(Exception):
    """Stands in for google.api_core.exceptions.AlreadyExists."""


class FakeAborted(Exception):
    """Stands in for a Firestore transaction that kept conflicting and ran out of attempts."""


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

    def get(self, transaction=None):
        self._db.check_allowed(self._path)
        if transaction is not None:
            return transaction.get(self)
        return FakeSnapshot(self.id, self._db.store.get(self._path))

    def set(self, data):
        self._db.check_allowed(self._path)
        with self._db.lock:
            self._db.apply("set", self._path, data)

    def create(self, data):
        self._db.check_allowed(self._path)
        with self._db.lock:
            if self._path in self._db.store:
                raise FakeAlreadyExists(self.path)
            self._db.apply("create", self._path, data)

    def delete(self):
        self._db.check_allowed(self._path)
        with self._db.lock:
            self._db.apply("delete", self._path)

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


class FakeTransaction:
    """Optimistic transaction like Firestore's: reads record the version they saw, writes are buffered until commit.
    As in Firestore, every read must come before the first write."""

    def __init__(self, db):
        self._db = db
        self.reads = {}  # path -> version seen
        self.ops = []  # buffered ("set" | "delete", ref, data)

    def get(self, ref):
        if self.ops:
            raise AssertionError("a transaction must read before it writes")
        with self._db.lock:
            self.reads[ref._path] = self._db.versions.get(ref._path, 0)
            snap = FakeSnapshot(ref.id, self._db.store.get(ref._path))
        if self._db.after_txn_read is not None:
            self._db.after_txn_read(ref._path)
        return snap

    def set(self, ref, data):
        self._db.check_allowed(ref._path)
        self.ops.append(("set", ref, copy.deepcopy(data)))

    def delete(self, ref):
        self._db.check_allowed(ref._path)
        self.ops.append(("delete", ref, None))


class FakeFirestore:
    conflict_errors = (FakeAborted,)

    def __init__(self):
        self.store = {}
        self.writes = []  # [("set" | "create" | "delete", path_tuple), ...]
        self.versions = {}  # path -> number of writes so far (plain writes and transaction commits)
        self.lock = threading.RLock()
        self.after_txn_read = None  # test hook: called with the path after every transactional read
        self.txn_attempts = 0  # total attempts made by run_in_transaction (for tests)
        self.forbidden = []  # path prefixes (tuples) that must never be read: any access raises AssertionError
        self.counter = itertools.count(1)

    def check_allowed(self, path):
        for prefix in self.forbidden:
            if path[:len(prefix)] == prefix:
                raise AssertionError("forbidden Firestore access: " + "/".join(path))

    def apply(self, op, path, data=None):
        """Write one document and bump its version. Callers hold self.lock."""
        self.writes.append((op, path))
        self.versions[path] = self.versions.get(path, 0) + 1
        if op == "delete":
            self.store.pop(path, None)
        else:
            self.store[path] = copy.deepcopy(data)

    def collection(self, name):
        return FakeCollection(self, (name,))

    def batch(self):
        return FakeBatch(self)

    def run_in_transaction(self, work):
        """Run work(txn); commit only if no document it read changed meanwhile, otherwise discard and retry."""
        for _attempt in range(MAX_TXN_ATTEMPTS):
            self.txn_attempts += 1
            txn = FakeTransaction(self)
            result = work(txn)  # an exception here discards the buffer: nothing is written
            with self.lock:
                if all(self.versions.get(path, 0) == seen for path, seen in txn.reads.items()):
                    for op, ref, data in txn.ops:
                        self.apply(op, ref._path, data)
                    return result
        raise FakeAborted(f"transaction failed after {MAX_TXN_ATTEMPTS} attempts")


def fake_verifier(token):
    """'token-alice' is a valid token for user 'alice'. Anything else is rejected like an invalid Firebase token."""
    if token.startswith("token-"):
        uid = token[len("token-"):]
        return {"uid": uid, "email": f"{uid}@example.com", "name": uid.capitalize()}
    raise ValueError("invalid token")
