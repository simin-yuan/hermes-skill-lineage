"""Text features compared between a skill write and its possible sources.

- shingles: every run of 8 consecutive word tokens, hashed with the per-install key (8 bytes);
- anchors: operative tokens a payload must keep to change behaviour — URLs and their hosts, a shell
  command with its first non-flag argument, package installs, file paths, environment variables,
  IP addresses and e-mail addresses — hashed with the same key.

Only hashes leave this module. Nothing here keeps text.
"""

from __future__ import annotations

import hashlib
import re

SHINGLE_TOKENS = 8

_WORD = re.compile(r"\w+", re.UNICODE)
_URL = re.compile(r"\b(?:https?|ftp)://[^\s\"'<>`)\]}]+", re.IGNORECASE)
# The local part is bounded (RFC 5321 caps it at 64 octets) and anchored behind a lookbehind instead of
# \b, so a long run of word characters cannot be re-scanned from every offset. The unbounded
# `\b[\w.+-]+@` form was quadratic on hostile input: 40 KB of "a." took 4.2 s and 200 KB took 108 s,
# while results inside a tool call are capped at 2 MB and `re` cannot be interrupted.
# The lookbehind cannot tell a separator from the first character of a local part, so a leading ".", "+"
# or "-" is removed where the match is used (anchor_strings): "-name@example.com" is the same address to
# a reader as "name@example.com", and the older pattern produced the second form, so anchors recorded
# before this version stay comparable instead of splitting one address into two hashes.
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]+(?:\.[\w-]+)+\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_ENV = re.compile(r"\$\{?([A-Z_][A-Z0-9_]{2,})\}?|\b([A-Z][A-Z0-9_]{3,})=")
_PATH = re.compile(r"(?<![\w/:])(?:~|\.{1,2})?(?:/[\w.@-]+){2,}/?|\b[A-Za-z]:\\(?:[\w.@ -]+\\)*[\w.@-]+")
_COMMANDS = ("curl", "wget", "bash", "sh", "zsh", "python", "python3", "node", "npx", "uvx", "chmod", "chown",
             "rm", "ssh", "scp", "nc", "ncat", "base64", "eval", "exec", "sudo", "docker", "kubectl", "git",
             "powershell", "pwsh", "iex", "invoke-webrequest", "invoke-expression", "certutil", "crontab",
             "systemctl", "launchctl", "reg", "schtasks", "openssl", "gpg", "export", "source", "dd", "mv", "cp")
_COMMAND = re.compile(r"(?:^|[\s;|&`$(])(" + "|".join(re.escape(c) for c in _COMMANDS) + r")((?:\s+[^\s;|&`]+){1,6})",
                      re.IGNORECASE | re.MULTILINE)
_INSTALL = re.compile(r"\b(pip3?|uv\s+pip|npm|pnpm|yarn|gem|cargo|go|brew|apt(?:-get)?|choco|winget)\s+"
                      r"(?:install|add|get)\s+((?:[^\s;|&`]+\s*){1,4})", re.IGNORECASE)
_TRAILING = ".,;:!?\"')]}>`"
_PACKAGE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._@/\-\[\],=<>!~+]*$")
_PLAIN_WORDS = frozenset(("and or then to the a an with from before after so in on of for if when that this "
                          "it is be as at by into your our their run use set it's").split())


def _operative_arg(arg: str) -> bool:
    """A command argument worth anchoring: looks like a URL, path, file, host, variable or option value —
    not a plain English word that happens to follow the command ("| bash so the caches ...")."""
    if not arg or arg.lower() in _PLAIN_WORDS:
        return False
    return bool(re.search(r"[/.:$~=@\\]", arg)) or bool(re.search(r"\w-\w|\d", arg))


def keyed(key: bytes, text: str, size: int = 8) -> bytes:
    return hashlib.blake2b(text.encode("utf-8"), key=key, digest_size=size).digest()


def keyed_hex(key: bytes, text: str, size: int = 16) -> str:
    return keyed(key, text, size).hex()


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


def shingles(key: bytes, text: str) -> set[bytes]:
    words = tokens(text)
    if len(words) < SHINGLE_TOKENS:
        return set()
    return {keyed(key, " ".join(words[i:i + SHINGLE_TOKENS])) for i in range(len(words) - SHINGLE_TOKENS + 1)}


def _clean(value: str) -> str:
    return value.strip().rstrip(_TRAILING).strip()


def anchor_strings(text: str) -> set[str]:
    """Normalised operative tokens (plain text; callers hash them immediately)."""
    text = text or ""
    found: set[str] = set()
    for match in _URL.finditer(text):
        url = _clean(match.group(0))
        if len(url) > 10:
            found.add("url:" + url.lower())
            host = re.sub(r"^[a-z]+://", "", url.lower()).split("/")[0].split("@")[-1].split(":")[0]
            if "." in host:
                found.add("host:" + host)
    for match in _EMAIL.finditer(text):
        address = match.group(0).lower().lstrip("+-.")
        if address:  # a local part made only of separators is not an address
            found.add("email:" + address)
    for match in _IP.finditer(text):
        parts = match.group(0).split(".")
        if all(0 <= int(p) <= 255 for p in parts) and match.group(0) not in ("0.0.0.0", "127.0.0.1"):
            found.add("ip:" + match.group(0))
    for match in _ENV.finditer(text):
        name = match.group(1) or match.group(2)
        found.add("env:" + name)
    for match in _PATH.finditer(text):
        path = _clean(match.group(0))
        if len(path) > 4 and not path.lower().startswith(("http", "//")):
            found.add("path:" + path)
    for match in _COMMAND.finditer(text):
        command = match.group(1).lower()
        args = [_clean(a) for a in match.group(2).split()]
        target = next((a for a in args if a and not a.startswith("-")), "")
        if _operative_arg(target):
            found.add(f"cmd:{command} {target.lower()}")
    for match in _INSTALL.finditer(text):
        manager = re.sub(r"\s+", " ", match.group(1).lower())
        for package in match.group(2).split():
            package = _clean(package)
            if package.startswith("-"):
                continue  # an option such as --upgrade
            if package.lower() in _PLAIN_WORDS or not _PACKAGE.match(package):
                break  # the package list ended ("pip install foo and export ...")
            found.add(f"pkg:{manager} {package.lower()}")
    return found


def url_hash(key: bytes, url: str) -> str:
    """Keyed hash of a URL, normalised the way anchor_strings normalises URLs in text."""
    return keyed_hex(key, "url:" + _clean(url).lower())


def anchors(key: bytes, text: str) -> set[str]:
    return {keyed_hex(key, value) for value in anchor_strings(text)}
