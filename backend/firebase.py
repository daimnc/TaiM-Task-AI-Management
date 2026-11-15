import firebase_admin
from firebase_admin import credentials, firestore

from config import Config


firebase_app = None
db = None


def initialize_firebase():
    global firebase_app, db

    if firebase_app is not None:
        return db

    if not Config.FIREBASE_PROJECT_ID:
        print("Firebase is not configured. Running without Firestore.")
        return None

    if not firebase_admin._apps:
        credential_path = Config.BASE_DIR / "keys" / "serviceAccount.json"

        if not credential_path.exists():
            print("Firebase service account key not found.")
            return None

        credential = credentials.Certificate(str(credential_path))

        firebase_app = firebase_admin.initialize_app(
            credential,
            {
                "projectId": Config.FIREBASE_PROJECT_ID
            }
        )
    else:
        firebase_app = firebase_admin.get_app()

    db = firestore.client(app=firebase_app)

    print("Firebase connected successfully.")

    return db