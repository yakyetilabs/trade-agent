"""GCP client singletons.

Every Google Cloud SDK client is instantiated exactly once here and reused across
the application. Never construct these clients inside a route handler or graph node.

Initialization is lazy (first call, memoized) so that *importing* this module has no
side effects and needs no credentials. That keeps the unauthenticated ``/health``
path and the unit-test suite credential-free, while still guaranteeing a single
instance per process.

The google-genai (Vertex AI) client singleton lives here too, per the
single-source-of-clients rule.
"""

from functools import lru_cache

import firebase_admin
from firebase_admin import App, credentials
from google import genai
from google.cloud.firestore import Client as FirestoreClient

from src.config import GCP_PROJECT, GCP_REGION


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


@lru_cache(maxsize=1)
def get_genai_client() -> genai.Client:
    """Return the singleton google-genai client pointed at Vertex AI.

    ``vertexai=True`` + project/location selects the Vertex backend over the Gemini
    Developer API; credentials come from ADC. Construction is lazy (memoized on first
    call), so importing this module needs no credentials.
    """
    return genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
