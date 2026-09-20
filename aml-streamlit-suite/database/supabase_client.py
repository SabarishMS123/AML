"""
Supabase client singleton for the AML Compliance Suite.

Loads credentials from environment variables (.env) and exposes a single
shared `supabase` client instance used across all services.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client instance.

    Raises a clear error if credentials are missing so the Streamlit app
    can surface a friendly message instead of a stack trace.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_KEY must be set in your .env file. "
            "Copy .env.example to .env and fill in your project credentials."
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# Convenience module-level accessor used by services (lazy — only connects
# when first accessed, so importing this module never fails on its own).
class _LazyClient:
    def __getattr__(self, name):
        return getattr(get_supabase_client(), name)


supabase = _LazyClient()
