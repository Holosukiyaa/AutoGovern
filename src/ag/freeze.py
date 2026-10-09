"""Freeze tracked canonical files while a task is open.

Windows adds a recoverable ACL deny-write entry for the current user.
Other systems clear the user-write bit. Both are strong friction against
accidental edits, not an absolute security boundary.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


# FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA | FILE_WRITE_ATTRIBUTES | DELETE.
# WRITE_DAC and WRITE_OWNER stay off this mask so thaw can remove the entry.
_DENY_WRITE_MASK = 0x0002 | 0x0004 | 0x0010 | 0x0100 | 0x00010000
_ACL_LIMIT = 65528


def _tracked_files(root: Path) -> list[Path]:
    ran = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out: list[Path] = []
    for line in (ran.stdout or "").splitlines():
        rel = line.strip().strip('"')
        if not rel:
            continue
        path = root / rel.replace("/", os.sep)
        if not path.is_file():
            continue
        if ".git" in set(path.resolve().parts):
            continue
        out.append(path)
    return out


def _force_user_write_bit(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
    except OSError:
        return


def _freeze_readonly_bit(root: Path) -> None:
    root = Path(root)
    for path in _tracked_files(root):
        try:
            path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
        except OSError:
            continue


def _thaw_readonly_bit(root: Path) -> None:
    root = Path(root)
    for path in _tracked_files(root):
        _force_user_write_bit(path)


def write_guard(path: Path) -> str:
    """Return ``acl-deny``, ``readonly-bit``, or ``none`` for one file."""
    path = Path(path)
    if os.name == "nt" and _deny_ace_count(path):
        return "acl-deny"
    if not (path.stat().st_mode & stat.S_IWRITE):
        return "readonly-bit"
    return "none"


def freeze_canonical(root: Path) -> None:
    """Freeze tracked canonical files. Does not touch .git, worktree, or AG_HOME."""
    root = Path(root)
    if os.name == "nt":
        _freeze_windows(root)
        return
    _freeze_readonly_bit(root)


def thaw_canonical(root: Path) -> None:
    """Remove this module's freeze and restore the user-write bit."""
    root = Path(root)
    if os.name == "nt":
        _thaw_windows(root)
        return
    _thaw_readonly_bit(root)


def _freeze_windows(root: Path) -> None:
    user_sid = _current_user_sid()
    for path in _tracked_files(root):
        _force_user_write_bit(path)
        _rewrite_dacl(path, user_sid, add_deny=True)
        if write_guard(path) != "acl-deny":
            raise OSError(f"freeze did not install ACL deny-write: {path}")


def _thaw_windows(root: Path) -> None:
    try:
        user_sid = _current_user_sid()
    except OSError:
        user_sid = None
    for path in _tracked_files(root):
        if user_sid is not None:
            try:
                _rewrite_dacl(path, user_sid, add_deny=False)
            except OSError:
                pass
        _force_user_write_bit(path)


def _deny_ace_count(path: Path) -> int:
    try:
        user_sid = _current_user_sid()
        aces = _explicit_aces(path, user_sid)
    except OSError:
        return 0
    return sum(1 for kind, mask, ours in aces if kind == "deny" and mask == _DENY_WRITE_MASK and ours)


_WIN: dict | None = None


def _win():
    global _WIN
    if _WIN is not None:
        return _WIN
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dword = wintypes.DWORD
    word = wintypes.WORD
    byte = wintypes.BYTE
    handle = wintypes.HANDLE
    psid = ctypes.c_void_p
    pacl = ctypes.c_void_p
    psecurity = ctypes.c_void_p

    class _AceHeader(ctypes.Structure):
        _fields_ = [("AceType", byte), ("AceFlags", byte), ("AceSize", word)]

    class _Acl(ctypes.Structure):
        _fields_ = [
            ("AclRevision", byte),
            ("Sbz1", byte),
            ("AclSize", word),
            ("AceCount", word),
            ("Sbz2", word),
        ]

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", psid), ("Attributes", dword)]

    class _TokenUser(ctypes.Structure):
        _fields_ = [("User", _SidAndAttributes)]

    kernel32.GetCurrentProcess.restype = handle
    kernel32.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
    kernel32.OpenProcessToken.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [handle]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.GetTokenInformation.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.POINTER(dword)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.CopySid.argtypes = [dword, psid, psid]
    advapi32.CopySid.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [psid]
    advapi32.GetLengthSid.restype = dword
    advapi32.EqualSid.argtypes = [psid, psid]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.InitializeAcl.argtypes = [pacl, dword, dword]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessDeniedAce.argtypes = [pacl, dword, dword, psid]
    advapi32.AddAccessDeniedAce.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAce.argtypes = [pacl, dword, dword, psid]
    advapi32.AddAccessAllowedAce.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [pacl, dword, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.AddAce.argtypes = [pacl, dword, dword, ctypes.c_void_p, dword]
    advapi32.AddAce.restype = wintypes.BOOL
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        dword,
        ctypes.POINTER(psid),
        ctypes.POINTER(psid),
        ctypes.POINTER(pacl),
        ctypes.POINTER(pacl),
        ctypes.POINTER(psecurity),
    ]
    advapi32.GetNamedSecurityInfoW.restype = dword
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        dword,
        psid,
        psid,
        pacl,
        pacl,
    ]
    advapi32.SetNamedSecurityInfoW.restype = dword
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(psid)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _WIN = {
        "ctypes": ctypes,
        "advapi32": advapi32,
        "kernel32": kernel32,
        "dword": dword,
        "AceHeader": _AceHeader,
        "Acl": _Acl,
        "TokenUser": _TokenUser,
    }
    return _WIN


def _win_error(prefix: str, code: int | None = None) -> OSError:
    import ctypes

    err = ctypes.get_last_error() if code is None else code
    return OSError(err, f"{prefix}: {ctypes.WinError(err)}")


def _current_user_sid():
    api = _win()
    kernel32 = api["kernel32"]
    advapi32 = api["advapi32"]
    handle = api["ctypes"].wintypes.HANDLE()
    if not kernel32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, api["ctypes"].byref(handle)):
        raise _win_error("OpenProcessToken")
    try:
        needed = api["dword"](0)
        advapi32.GetTokenInformation(handle, 1, None, 0, api["ctypes"].byref(needed))
        buf = api["ctypes"].create_string_buffer(max(int(needed.value), 1))
        if not advapi32.GetTokenInformation(handle, 1, buf, api["dword"](len(buf)), api["ctypes"].byref(needed)):
            raise _win_error("GetTokenInformation")
        user = api["ctypes"].cast(buf, api["ctypes"].POINTER(api["TokenUser"])).contents
        length = int(advapi32.GetLengthSid(user.User.Sid))
        sid_buf = api["ctypes"].create_string_buffer(length)
        if not advapi32.CopySid(length, sid_buf, user.User.Sid):
            raise _win_error("CopySid")
        return sid_buf
    finally:
        kernel32.CloseHandle(handle)


def _file_security(path: Path):
    api = _win()
    owner = api["ctypes"].c_void_p()
    group = api["ctypes"].c_void_p()
    dacl = api["ctypes"].c_void_p()
    sacl = api["ctypes"].c_void_p()
    descriptor = api["ctypes"].c_void_p()
    code = api["advapi32"].GetNamedSecurityInfoW(
        _win_path(path),
        1,
        0x4,
        api["ctypes"].byref(owner),
        api["ctypes"].byref(group),
        api["ctypes"].byref(dacl),
        api["ctypes"].byref(sacl),
        api["ctypes"].byref(descriptor),
    )
    if code != 0:
        raise _win_error(f"GetNamedSecurityInfoW {path}", int(code))
    return dacl, descriptor


def _win_path(path: Path) -> str:
    text = str(path.resolve())
    if text.startswith("\\\\?\\") or len(text) < 240:
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def _ace_fields(api, address: int) -> tuple[int, int, int, int]:
    header = api["AceHeader"].from_address(address)
    mask = api["ctypes"].c_uint32.from_address(address + api["ctypes"].sizeof(api["AceHeader"])).value
    return int(header.AceType), int(header.AceFlags), int(header.AceSize), int(mask)


def _is_our_deny(api, address: int, user_sid, ace_type: int, flags: int, size: int, mask: int) -> bool:
    if ace_type != 1 or flags & 0x10 or mask != _DENY_WRITE_MASK or size < 8:
        return False
    sid = api["ctypes"].c_void_p(address + 8)
    return bool(api["advapi32"].EqualSid(sid, user_sid))


def _explicit_aces(path: Path, user_sid) -> list[tuple[str, int, bool]]:
    api = _win()
    dacl, descriptor = _file_security(path)
    try:
        if not dacl or not dacl.value:
            return []
        found: list[tuple[str, int, bool]] = []
        count = int(api["Acl"].from_address(dacl.value).AceCount)
        for index in range(count):
            ace = api["ctypes"].c_void_p()
            if not api["advapi32"].GetAce(dacl, index, api["ctypes"].byref(ace)):
                raise _win_error(f"GetAce {path}")
            address = int(ace.value or 0)
            ace_type, flags, size, mask = _ace_fields(api, address)
            if flags & 0x10:
                continue
            kind = {0: "allow", 1: "deny"}.get(ace_type, "other")
            ours = False
            if ace_type in (0, 1) and size >= 8:
                ours = bool(api["advapi32"].EqualSid(api["ctypes"].c_void_p(address + 8), user_sid))
            found.append((kind, mask, ours))
        return found
    finally:
        if descriptor and descriptor.value:
            api["kernel32"].LocalFree(descriptor)


def _rewrite_dacl(path: Path, user_sid, *, add_deny: bool) -> None:
    api = _win()
    dacl, descriptor = _file_security(path)
    acl_buf = None
    try:
        kept: list[tuple[int, int]] = []
        has_ours = False
        if dacl and dacl.value:
            count = int(api["Acl"].from_address(dacl.value).AceCount)
            for index in range(count):
                ace = api["ctypes"].c_void_p()
                if not api["advapi32"].GetAce(dacl, index, api["ctypes"].byref(ace)):
                    raise _win_error(f"GetAce {path}")
                address = int(ace.value or 0)
                ace_type, flags, size, mask = _ace_fields(api, address)
                if _is_our_deny(api, address, user_sid, ace_type, flags, size, mask):
                    has_ours = True
                    continue
                if flags & 0x10:
                    continue
                kept.append((address, size))
        if add_deny and has_ours:
            return
        if not add_deny and not has_ours:
            return
        extra = 8 + int(api["advapi32"].GetLengthSid(user_sid)) + 64
        total = 8 + extra + sum(size for _, size in kept) + 32
        if not dacl or not dacl.value:
            total += 96
        if total > _ACL_LIMIT:
            raise OSError(f"ACL is too large to rewrite: {path}")
        total = max(total, 256)
        acl_buf = api["ctypes"].create_string_buffer(total)
        if not api["advapi32"].InitializeAcl(acl_buf, total, 2):
            raise _win_error(f"InitializeAcl {path}")
        if add_deny and not api["advapi32"].AddAccessDeniedAce(acl_buf, 2, _DENY_WRITE_MASK, user_sid):
            raise _win_error(f"AddAccessDeniedAce {path}")
        for address, size in kept:
            if not api["advapi32"].AddAce(acl_buf, 2, 0xFFFFFFFF, address, size):
                raise _win_error(f"AddAce {path}")
        if (not dacl or not dacl.value) and add_deny:
            everyone = api["ctypes"].c_void_p()
            if not api["advapi32"].ConvertStringSidToSidW("S-1-1-0", api["ctypes"].byref(everyone)):
                raise _win_error(f"ConvertStringSidToSidW {path}")
            try:
                if not api["advapi32"].AddAccessAllowedAce(acl_buf, 2, 0x10000000, everyone):
                    raise _win_error(f"AddAccessAllowedAce {path}")
            finally:
                if everyone.value:
                    api["kernel32"].LocalFree(everyone)
    finally:
        if descriptor and descriptor.value:
            api["kernel32"].LocalFree(descriptor)
    if acl_buf is None:
        return
    name = api["ctypes"].create_unicode_buffer(_win_path(path))
    code = api["advapi32"].SetNamedSecurityInfoW(
        name,
        1,
        0x4 | 0x20000000,
        None,
        None,
        acl_buf,
        None,
    )
    if code != 0:
        raise _win_error(f"SetNamedSecurityInfoW {path}", int(code))


def freeze_worktree(root: Path) -> None:
    """Freeze tracked worktree files until the intent map is confirmed."""
    _freeze_windows(Path(root)) if os.name == "nt" else _freeze_readonly_bit(Path(root))


def thaw_worktree(root: Path) -> None:
    """Remove the intent-map freeze from a worktree."""
    _thaw_windows(Path(root)) if os.name == "nt" else _thaw_readonly_bit(Path(root))
