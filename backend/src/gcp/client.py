"""GCP client singletons.

Every Google Cloud SDK client is instantiated exactly once here and reused across
the application. Never construct these clients inside a route handler or graph node.

Initialization is lazy (first call, memoized) so that *importing* this module has no
side effects and needs no credentials. That keeps the unauthenticated ``/health``
path and the unit-test suite credential-free, while still guaranteeing a single
instance per process.

The Vertex AI singleton is added in the agent phase; it will live here too, per the
single-source-of-clients rule.
"""

from functools import lru_cache

import firebase_admin
from firebase_admin import App, credentials
from google.cloud.firestore import Client as FirestoreClient

from src.config import GCP_PROJECT


@lru_cache(maxsize=1)
def get_firebase_app() -> App:
    """Initialize the Firebase Admin app once (ADC / GOOGLE_APPLICATION_CREDENTIALS)."""
    return firebase_admin.initialize_app(
        credential=credentials.ApplicationDefault(),
        options={"projectId": GCP_PROJECT},
    )


@lru_cache(maxsize=1)
def get_firestore_client() -> FirestoreClient:
    """Return the singleton Firestore (Native mode) client."""
    return FirestoreClient(project=GCP_PROJECT)
