# Local yt-dlp plugin: unlock the Chrome/Edge cookie database on Windows.
#
# Vendored from https://github.com/seproDev/yt-dlp-ChromeCookieUnlock
# (MIT License, adapted from Charles Machalow's gist).
#
# yt-dlp auto-discovers this plugin because it lives in the `yt_dlp_plugins`
# namespace package on sys.path. On import it monkeypatches
# `yt_dlp.cookies._open_database_copy` so that, when yt-dlp cannot copy the
# cookie database because it is locked by the still-running browser (a
# PermissionError), we use the Windows Restart Manager to force-shut the
# locking processes and then retry the copy. This fixes the
# "Could not copy ... cookie database" error even while the browser is open.
#
# NOTE: this does NOT fix DPAPI decryption failures ("Failed to decrypt with
# DPAPI"), which are caused by running yt-dlp under a different Windows user
# than the browser. For that, run the app as the same user (not Administrator)
# or use a cookies.txt file.

import sys


def _patch() -> None:
    import yt_dlp.cookies

    original_func = yt_dlp.cookies._open_database_copy

    def unlock_chrome(database_path, tmpdir):
        try:
            return original_func(database_path, tmpdir)
        except PermissionError:
            print("Attempting to unlock cookies", file=sys.stderr)
            _unlock_cookies(database_path)
            return original_func(database_path, tmpdir)

    yt_dlp.cookies._open_database_copy = unlock_chrome


def _unlock_cookies(cookies_path) -> None:
    # Adapted from https://gist.github.com/csm10495/e89e660ffee0030e8ef410b793ad6a7e
    # By Charles Machalow under the MIT License
    from ctypes import windll, byref, create_unicode_buffer, pointer, WINFUNCTYPE
    from ctypes.wintypes import DWORD, WCHAR, UINT

    ERROR_SUCCESS = 0
    ERROR_MORE_DATA = 234
    RmForceShutdown = 1

    @WINFUNCTYPE(None, UINT)
    def callback(percent_complete: UINT) -> None:
        pass

    rstrtmgr = windll.LoadLibrary("Rstrtmgr")

    session_handle = DWORD(0)
    session_flags = DWORD(0)
    session_key = (WCHAR * 256)()

    result = DWORD(rstrtmgr.RmStartSession(
        byref(session_handle), session_flags, session_key)).value
    if result != ERROR_SUCCESS:
        raise RuntimeError(f"RmStartSession returned non-zero result: {result}")

    try:
        result = DWORD(rstrtmgr.RmRegisterResources(
            session_handle, 1,
            byref(pointer(create_unicode_buffer(cookies_path))),
            0, None, 0, None)).value
        if result != ERROR_SUCCESS:
            raise RuntimeError(f"RmRegisterResources returned non-zero result: {result}")

        proc_info_needed = DWORD(0)
        proc_info = DWORD(0)
        reboot_reasons = DWORD(0)

        result = DWORD(rstrtmgr.RmGetList(
            session_handle, byref(proc_info_needed),
            byref(proc_info), None, byref(reboot_reasons))).value
        if result not in (ERROR_SUCCESS, ERROR_MORE_DATA):
            raise RuntimeError(f"RmGetList returned non-successful result: {result}")

        if proc_info_needed.value:
            result = DWORD(rstrtmgr.RmShutdown(
                session_handle, RmForceShutdown, callback)).value
            if result != ERROR_SUCCESS:
                raise RuntimeError(f"RmShutdown returned non-zero result: {result}")
        else:
            print("File is not locked", file=sys.stderr)
    finally:
        result = DWORD(rstrtmgr.RmEndSession(session_handle)).value
        if result != ERROR_SUCCESS:
            raise RuntimeError(f"RmEndSession returned non-zero result: {result}")


if sys.platform == "win32":
    try:
        _patch()
    except Exception as exc:  # pragma: no cover - never break yt-dlp loading
        print(f"[ChromeCookieUnlock] disabled: {exc}", file=sys.stderr)
