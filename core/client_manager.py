# core/client_manager.py
import os
import json
from typing import Dict, List, Any, Optional

CLIENTS_FILE = os.path.join("data", "clients.json")


def _ensure_data_dir():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(CLIENTS_FILE):
        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)


def load_all_clients() -> Dict[str, Dict[str, Any]]:
    """Load all saved client profiles from data/clients.json."""
    _ensure_data_dir()
    try:
        with open(CLIENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_client(name: str, gstin: str, username: str = "") -> bool:
    """Save or update a client profile."""
    _ensure_data_dir()
    clients = load_all_clients()
    clean_name = (name or "").strip()
    if not clean_name:
        return False

    clients[clean_name] = {
        "client_name": clean_name,
        "client_gstin": (gstin or "").strip().upper(),
        "gst_username": (username or "").strip(),
    }

    try:
        with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(clients, f, indent=2)
        return True
    except Exception:
        return False


def delete_client(name: str) -> bool:
    """Delete a client profile from saved directory."""
    _ensure_data_dir()
    clients = load_all_clients()
    clean_name = (name or "").strip()
    if clean_name in clients:
        del clients[clean_name]
        try:
            with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(clients, f, indent=2)
            return True
        except Exception:
            return False
    return False