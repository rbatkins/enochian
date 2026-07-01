"""The fixed vocabulary of world powers.

This table IS the world. Crucially, none of these names is in scope as a
callable in the language: `read`, `write`, `send`, `now`, `gen` exist ONLY as
methods dispatched on a lease token. There is no global `read`. That is what
"the world starts empty" means, taken literally -- the vocabulary is
non-ambient, not merely the authority.

Each verb declares:
  domain    the effect domain it belongs to
  params    (name, type) of each argument
  ret       return type
  path_arg  index of a path-typed argument constrained by `path under`, or None
  host_arg  index of a host argument constrained by `host eq`, or None
  data_arg  index of a payload argument metered by `bytes_le` / `total_le`
"""

from __future__ import annotations

VERBS = {
    "read":  {"domain": "fs",    "params": [("path", "Text")],                 "ret": "Text",       "path_arg": 0,    "host_arg": None, "data_arg": None},
    "write": {"domain": "fs",    "params": [("path", "Text"), ("data", "Text")], "ret": "Unit",     "path_arg": 0,    "host_arg": None, "data_arg": 1},
    "list":  {"domain": "fs",    "params": [("dir", "Text")],                  "ret": "List[Text]", "path_arg": 0,    "host_arg": None, "data_arg": None},
    "send":  {"domain": "net",   "params": [("host", "Text"), ("data", "Text")], "ret": "Unit",     "path_arg": None, "host_arg": 0,    "data_arg": 1},
    "now":   {"domain": "clock", "params": [],                                 "ret": "Int",        "path_arg": None, "host_arg": None, "data_arg": None},
    "gen":   {"domain": "rand",  "params": [],                                 "ret": "Int",        "path_arg": None, "host_arg": None, "data_arg": None},
}

DOMAINS = {"fs", "net", "clock", "rand"}


def verbs_for_domain(domain: str) -> list[str]:
    return sorted(v for v, spec in VERBS.items() if spec["domain"] == domain)


def pred_applies_to_verb(pred_kind: str, verb: str) -> bool:
    spec = VERBS[verb]
    if pred_kind == "path":
        return spec["path_arg"] is not None
    if pred_kind == "host":
        return spec["host_arg"] is not None
    if pred_kind in ("bytes_le", "total_le"):
        return spec["data_arg"] is not None
    return False
