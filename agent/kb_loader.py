import os
import functools
import requests
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


@functools.lru_cache(maxsize=32)
def load_kb(project_slug: str) -> Dict[str, Any]:
    """
    Loads property Knowledge Base (KB) config from Supabase REST API by joining
    projects with tenants where tenants.slug matches project_slug.

    Args:
        project_slug: The tenant slug identifier (e.g. 'nxlyr-demo').

    Returns:
        dict: The project config JSONB dictionary per TRD §3.3 schema.

    Raises:
        ValueError: If required env vars are missing, no matching project is found,
                    or the returned KB config is invalid/empty.
        RuntimeError: If the HTTP request to Supabase fails.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables must be set"
        )

    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/projects"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Accept": "application/json",
    }

    # Single deterministic query: join tenants where tenants.slug matches project_slug
    params = {
        "select": "id,name,config,tenants!inner(slug)",
        "tenants.slug": f"eq.{project_slug}",
        "limit": "1",
    }

    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=10)
    except requests.RequestException as e:
        raise RuntimeError(f"Network error querying Supabase REST API for '{project_slug}': {e}") from e

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to query Supabase REST API for '{project_slug}': HTTP {response.status_code} - {response.text}"
        )

    rows = response.json()
    if not isinstance(rows, list) or len(rows) == 0:
        raise ValueError(f"No project KB found in Supabase matching tenant slug '{project_slug}'")

    project_data = rows[0]
    config = project_data.get("config")

    if not config or not isinstance(config, dict):
        raise ValueError(
            f"Project KB config for tenant slug '{project_slug}' (Project ID: {project_data.get('id')}) is empty or invalid"
        )

    return config
