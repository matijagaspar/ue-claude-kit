"""Minimal YAML subset reader/writer for ue_local_config.local (stdlib only, no PyYAML).

Supported: `#` comments, nested mappings by indentation, scalars (str, int, float,
bool, null), inline lists `[a, "b c"]` and block lists (`- item`). That is all the
config file uses, and it keeps the file readable by any YAML parser as well.
"""
import re

_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_BARE_OK = re.compile(r"^[A-Za-z0-9_./\\@+-][A-Za-z0-9_./\\@+ -]*$")


def _scalar(text):
    t = text.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if t[0] in "\"'":
        q = t[0]
        end = t.rfind(q)
        body = t[1:end]
        return body.replace('\\"', '"').replace("\\\\", "\\") if q == '"' else body.replace("''", "'")
    # strip trailing comment on unquoted values
    t = re.sub(r"\s+#.*$", "", t)
    if t in ("true", "True", "yes"):
        return True
    if t in ("false", "False", "no"):
        return False
    if _NUM.match(t):
        return float(t) if "." in t else int(t)
    if t.startswith("[") and t.endswith("]"):
        return _inline_list(t[1:-1])
    return t


def _inline_list(body):
    items, cur, quote = [], "", None
    for ch in body:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        items.append(cur)
    return [_scalar(i) for i in items if i.strip()]


def loads(text):
    root = {}
    # stack of (indent, container)
    stack = [(-1, root)]
    pending_key = None  # (indent, parent_dict, key) awaiting a nested block
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if pending_key and indent > pending_key[0]:
            _, parent, key = pending_key
            container = [] if stripped.startswith("- ") or stripped == "-" else {}
            parent[key] = container
            stack.append((pending_key[0], container))
        pending_key = None
        container = stack[-1][1]
        if stripped.startswith("- ") or stripped == "-":
            if isinstance(container, list):
                container.append(_scalar(stripped[1:]))
            continue
        m = re.match(r'^("[^"]*"|\'[^\']*\'|[^:]+?)\s*:(\s+(.*))?$', stripped)
        if not m or not isinstance(container, dict):
            raise ValueError("Unparseable config line: %r" % raw)
        key = _scalar(m.group(1))
        value = m.group(3)
        if value is None or re.sub(r"\s*#.*$", "", value) == "":
            container[key] = None
            pending_key = (indent, container, key)
        else:
            container[key] = _scalar(value)
    return root


def _fmt(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(i) for i in v) + "]"
    s = str(v)
    if (_BARE_OK.match(s) and not _NUM.match(s) and s not in ("true", "false", "null", "yes", "no", "~")
            and not s.endswith(" ") and ": " not in s and " #" not in s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(data, comments=None, header=None):
    """Serialize a nested dict. `comments` maps dotted key paths to a comment line
    emitted above that key, e.g. {"gpu.busy_util_percent": "..."}."""
    comments = comments or {}
    out = []
    if header:
        out += ["# " + l if l else "#" for l in header.splitlines()]
        out.append("")

    def walk(d, indent, prefix):
        for k, v in d.items():
            path = prefix + k
            pad = "  " * indent
            if path in comments:
                for c in comments[path].splitlines():
                    out.append(pad + "# " + c)
            if isinstance(v, dict):
                out.append("%s%s:" % (pad, k))
                walk(v, indent + 1, path + ".")
                if indent == 0:
                    out.append("")
            else:
                out.append("%s%s: %s" % (pad, k, _fmt(v)))

    walk(data, 0, "")
    return "\n".join(out).rstrip() + "\n"
