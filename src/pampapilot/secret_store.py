"""Windows user-scoped encrypted storage for local provider credentials."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from .media_discovery import WORKSPACE_ROOT


DEFAULT_SECRET_PATH = (
    WORKSPACE_ROOT / ".runtime" / "secrets" / "lmstudio-token.dpapi"
)
_ENTROPY = b"PampaPilot:LMStudio:v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretStoreError(RuntimeError):
    """The local encrypted credential could not be read or written."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    )
    return blob, buffer


def _crypt32() -> ctypes.WinDLL:
    if os.name != "nt":
        raise SecretStoreError("DPAPI credential storage is available only on Windows")
    return ctypes.WinDLL("crypt32", use_last_error=True)


def _protect_for_current_user(data: bytes) -> bytes:
    crypt32 = _crypt32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_blob, input_buffer = _input_blob(data)
    entropy_blob, entropy_buffer = _input_blob(_ENTROPY)
    output_blob = _DataBlob()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    success = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "PampaPilot LM Studio token",
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if not success:
        raise SecretStoreError(
            f"Windows could not encrypt the credential: {ctypes.get_last_error()}"
        )
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect_for_current_user(data: bytes) -> bytes:
    crypt32 = _crypt32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_blob, input_buffer = _input_blob(data)
    entropy_blob, entropy_buffer = _input_blob(_ENTROPY)
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    success = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = (input_buffer, entropy_buffer)
    if not success:
        raise SecretStoreError(
            f"Windows could not decrypt the credential: {ctypes.get_last_error()}"
        )
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if description:
            kernel32.LocalFree(description)
        kernel32.LocalFree(output_blob.pbData)


class WindowsSecretStore:
    def __init__(self, path: Path = DEFAULT_SECRET_PATH) -> None:
        self.path = path.resolve()

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, secret: str) -> None:
        if not secret:
            raise ValueError("secret cannot be empty")
        encrypted = _protect_for_current_user(secret.encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def load(self) -> str:
        if not self.path.is_file():
            return ""
        try:
            return _unprotect_for_current_user(self.path.read_bytes()).decode("utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise SecretStoreError("The stored credential is invalid") from exc

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
