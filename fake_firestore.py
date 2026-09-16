"""Cliente de Firestore 'falso', 100% en memoria — sin conexión a internet.

Se usa automáticamente cuando la plataforma todavía NO tiene configuradas las
credenciales de Firebase (archivo `serviceAccountKey.json`), para que puedas
seguir explorándola mientras terminas el Paso 2. En cuanto agregues tus
credenciales reales, la app se conecta sola a tu proyecto de Firebase de
verdad y deja de usar este modo de práctica.

Los datos de este modo viven solo mientras el servidor está corriendo: se
pierden al cerrar `streamlit run`.

Implementa el pequeño subconjunto de la API de `google.cloud.firestore` que
usa database.py: collection().document(), .add(), .where(==).stream(),
.stream(), get()/set()/update()/delete().
"""

import uuid

_STORE = {}  # {collection_name: {doc_id: {..data..}}}


def _coll(name):
    return _STORE.setdefault(name, {})


class DocumentSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = dict(data) if data is not None else None
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class DocumentRef:
    def __init__(self, collection_name, doc_id):
        self.collection_name = collection_name
        self.id = doc_id

    def set(self, data, merge=False):
        store = _coll(self.collection_name)
        if merge and self.id in store:
            store[self.id].update(data)
        else:
            store[self.id] = dict(data)

    def update(self, data):
        store = _coll(self.collection_name)
        if self.id not in store:
            raise KeyError(f"Documento no encontrado: {self.collection_name}/{self.id}")
        store[self.id].update(data)

    def get(self):
        store = _coll(self.collection_name)
        return DocumentSnapshot(self.id, store.get(self.id))

    def delete(self):
        store = _coll(self.collection_name)
        store.pop(self.id, None)


class Query:
    def __init__(self, collection_name, filters):
        self.collection_name = collection_name
        self.filters = filters

    def where(self, field, op, value):
        assert op == "==", "El cliente falso solo soporta comparaciones '=='"
        return Query(self.collection_name, self.filters + [(field, value)])

    def limit(self, n):
        return self

    def stream(self):
        store = _coll(self.collection_name)
        for doc_id, data in list(store.items()):
            if all(data.get(f) == v for f, v in self.filters):
                yield DocumentSnapshot(doc_id, data)


class CollectionRef(Query):
    def __init__(self, name):
        super().__init__(name, [])

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = uuid.uuid4().hex
        return DocumentRef(self.collection_name, doc_id)

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return (None, ref)


class FakeFirestoreClient:
    def collection(self, name):
        return CollectionRef(name)


def reset():
    """Limpia todos los datos en memoria (usado por las pruebas)."""
    _STORE.clear()
