#!/usr/bin/env python3
"""Shared path resolution for the pipeline.

The public repo ships BLANK defaults. A reader's real data lives on the
mounted volume (CFG_DIR — /config on Unraid, container/config locally):
  library.json · sequels.json · seed-reads.json · taste-prompt.md

Resolution order for every personal file: the volume first, then the repo
copy (blank on a fresh install). Runtime outputs (months, candidates,
caches) live in pipeline/data.
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

_REPO_PATHS = {
    'library.json': os.path.join(ROOT, 'data', 'library.json'),
    'sequels.json': os.path.join(ROOT, 'data', 'sequels.json'),
    'seed-reads.json': os.path.join(ROOT, 'seed-reads.json'),
    'taste-prompt.md': os.path.join(BASE, 'taste-prompt.md'),
}


def cfg_dir():
    """Mirror container/server.py: CFG_DIR env -> /config (the Unraid volume) ->
    the local container/config."""
    d = os.environ.get('CFG_DIR')
    if d:
        return d
    if os.path.isdir('/config') and os.access('/config', os.W_OK):
        return '/config'
    return os.path.join(ROOT, 'container', 'config')


def personal(name):
    """(path, source) for a personal-data file: volume first, repo fallback.
    source: 'config' | 'repo' | 'missing' (callers decide what missing means)."""
    vol = os.path.join(cfg_dir(), name)
    if os.path.exists(vol):
        return vol, 'config'
    repo = _REPO_PATHS.get(name, os.path.join(ROOT, name))
    if os.path.exists(repo):
        return repo, 'repo'
    return repo, 'missing'
