"""This module provides logging utilities."""

from supabase import create_client, Client
import os

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase: Client | None

if url and key:
    supabase = create_client(url, key)
else:
    supabase = None

def log_query(query_type, params):
    """Send query logs to Supabase."""
    if supabase:
        supabase.table("WestieMusicDatabase").insert( {
            "query_type": query_type,
            "params": params,
        }).execute()
