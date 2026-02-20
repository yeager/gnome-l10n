"""GNOME l10n.gnome.org API client with caching."""

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Callable

API_BASE = "https://l10n.gnome.org/api/v1"

def get_cache_dir():
    p = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gnome-l10n"
    p.mkdir(parents=True, exist_ok=True)
    return p

CACHE_FILE = get_cache_dir() / "stats_cache.json"
CACHE_MAX_AGE = 3600  # 1 hour


@dataclass
class ModuleStats:
    """Translation stats for one GNOME module/domain."""
    module: str
    branch: str
    domain: str = "po"
    language: str = "sv"
    translated: int = 0
    fuzzy: int = 0
    untranslated: int = 0
    state: str = ""
    po_file: str = ""
    pot_file: str = ""

    @property
    def total(self):
        return self.translated + self.fuzzy + self.untranslated

    @property
    def pct(self):
        return (self.translated / self.total * 100) if self.total > 0 else 0.0

    @property
    def complete(self):
        return self.fuzzy == 0 and self.untranslated == 0 and self.total > 0


def _fetch_json(url):
    """Fetch JSON from URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "gnome-l10n/0.1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_releases():
    """Get list of GNOME releases."""
    data = _fetch_json(f"{API_BASE}/releases/")
    return data


def get_release_stats(release, language="sv"):
    """Get module list for a release+language."""
    data = _fetch_json(f"{API_BASE}/releases/{release}/languages/{language}")
    return data


def get_module_stats(module, branch, domain, language="sv"):
    """Get detailed stats for one module."""
    url = f"{API_BASE}/modules/{module}/branches/{branch}/domains/{domain}/languages/{language}"
    data = _fetch_json(url)
    stats = data.get("statistics", {})
    return ModuleStats(
        module=data.get("module", module),
        branch=data.get("branch", branch),
        domain=data.get("domain", domain),
        language=data.get("language", language),
        translated=stats.get("trans", 0),
        fuzzy=stats.get("fuzzy", 0),
        untranslated=stats.get("untrans", 0),
        state=data.get("state", ""),
        po_file=data.get("po_file", ""),
        pot_file=data.get("pot_file", ""),
    )


def fetch_all_stats(release, language="sv", progress_cb=None):
    """Fetch stats for all modules in a release. Returns list of ModuleStats."""
    data = get_release_stats(release, language)
    modules = data.get("modules", [])
    results = []

    for i, m in enumerate(modules):
        stats_path = m.get("stats", "")
        if not stats_path:
            continue
        try:
            url = f"https://l10n.gnome.org{stats_path}"
            d = _fetch_json(url)
            s = d.get("statistics", {})
            ms = ModuleStats(
                module=d.get("module", m.get("module", "")),
                branch=d.get("branch", m.get("branch", "")),
                domain=d.get("domain", "po"),
                language=language,
                translated=s.get("trans", 0),
                fuzzy=s.get("fuzzy", 0),
                untranslated=s.get("untrans", 0),
                state=d.get("state", ""),
                po_file=d.get("po_file", ""),
                pot_file=d.get("pot_file", ""),
            )
            results.append(ms)
        except Exception:
            pass

        if progress_cb:
            progress_cb(i + 1, len(modules))

        # Rate limit
        time.sleep(0.1)

    return results


def save_cache(release, language, stats):
    """Save stats to cache."""
    data = {
        "release": release,
        "language": language,
        "timestamp": time.time(),
        "stats": [asdict(s) for s in stats],
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_cache(release, language):
    """Load stats from cache if fresh enough."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        if data.get("release") != release or data.get("language") != language:
            return None
        if time.time() - data.get("timestamp", 0) > CACHE_MAX_AGE:
            return None
        return [ModuleStats(**s) for s in data.get("stats", [])]
    except Exception:
        return None
