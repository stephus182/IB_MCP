"""
Human authentication gate using macOS Touch ID.

SECURITY DESIGN
---------------
- Fail closed: ANY error, timeout, or biometric unavailability raises
  AuthDeniedError. There is no code path that returns approval without a
  live fingerprint scan.
- No caching: every call requires a fresh scan. There is no "valid for N
  minutes" window that could be exploited.
- Audit log: every attempt (approved or denied) is written to disk BEFORE
  this function returns, so the log cannot be bypassed by catching the
  exception.

INTENDED USE
------------
This gate must be called immediately before any live order is submitted to
IBKR. The caller must not catch AuthDeniedError to proceed — catching it
to work around the gate is a security violation.

    gate = AuthGate()
    try:
        gate.require("BUY 100 AAPL @ $185.00")
    except AuthDeniedError:
        return   # order is NOT sent
    ibkr_client.place_order(...)   # only reached after live fingerprint
"""
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

if sys.platform != "darwin":
    raise ImportError("auth_gate requires macOS — Touch ID is not available on this platform")

try:
    from LocalAuthentication import (
        LAContext,
        LAPolicyDeviceOwnerAuthenticationWithBiometrics,
    )
    _LA_AVAILABLE = True
except ImportError:
    _LA_AVAILABLE = False

_AUDIT_LOG = Path.home() / ".ibkr_core" / "auth_audit.log"
_TOUCH_ID_TIMEOUT = 30.0  # seconds before the prompt is considered abandoned


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthDeniedError(Exception):
    """
    Raised when Touch ID validation fails, is denied, times out, or is
    unavailable. This exception MUST propagate — it must never be caught
    to allow an order to proceed.
    """


class AuthUnavailableError(AuthDeniedError):
    """Touch ID hardware or framework is not available on this machine."""


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    approved: bool
    action: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    error: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_audit(result: AuthResult) -> None:
    """Append one line to the audit log. Never raises — a log failure must
    not silently suppress the AuthDeniedError that follows."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        status = "APPROVED" if result.approved else "DENIED"
        line = f"{result.timestamp.isoformat()} | {status} | {result.action}"
        if result.error:
            line += f" | error={result.error}"
        with _AUDIT_LOG.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass  # audit failure is logged nowhere — it must not mask the denial


def _evaluate_touch_id(reason: str) -> tuple[bool, str]:
    """
    Synchronously invoke the macOS LocalAuthentication biometric prompt.
    Returns (success: bool, error_message: str).

    Fail closed: returns (False, ...) on any error — never (True, ...) unless
    the user's fingerprint was physically verified by the Secure Enclave.
    """
    if not _LA_AVAILABLE:
        return False, (
            "pyobjc-framework-LocalAuthentication is not installed. "
            "Run: pip install pyobjc-framework-LocalAuthentication"
        )

    ctx = LAContext.new()
    can_eval, err = ctx.canEvaluatePolicy_error_(
        LAPolicyDeviceOwnerAuthenticationWithBiometrics, None
    )
    if not can_eval:
        return False, f"Touch ID unavailable: {err}"

    # The framework callback fires on a background thread; use an Event to
    # make this function synchronous.
    outcome: dict = {"success": False, "error_msg": ""}
    done = threading.Event()

    def _reply(success, error):
        outcome["success"] = bool(success)
        outcome["error_msg"] = str(error) if error else ""
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(
        LAPolicyDeviceOwnerAuthenticationWithBiometrics,
        reason,
        _reply,
    )

    if not done.wait(timeout=_TOUCH_ID_TIMEOUT):
        return False, f"Touch ID prompt timed out after {int(_TOUCH_ID_TIMEOUT)}s"

    return outcome["success"], outcome["error_msg"]


# ── Public interface ──────────────────────────────────────────────────────────

class AuthGate:
    """
    Human authentication gate using macOS Touch ID.

    Instantiate once and call require() before every live order action.
    """

    def require(self, action: str) -> AuthResult:
        """
        Require Touch ID approval for the described action.

        The action string is shown directly in the macOS Touch ID prompt —
        be specific so the user knows exactly what they are authorising.

        Returns:
            AuthResult with approved=True if the fingerprint was verified.

        Raises:
            AuthDeniedError: fingerprint denied, timed out, or unavailable.
            AuthUnavailableError (subclass of AuthDeniedError): hardware or
                framework not present.

        Example:
            gate.require("BUY 100 AAPL @ $185.00 — IBKR live order")
        """
        reason = f"IBKR order authorisation: {action}"

        try:
            success, error_msg = _evaluate_touch_id(reason)
        except Exception as exc:
            result = AuthResult(approved=False, action=action, error=str(exc))
            _write_audit(result)
            raise AuthDeniedError(f"Touch ID evaluation raised an exception: {exc}") from exc

        result = AuthResult(approved=success, action=action, error=error_msg)
        _write_audit(result)

        if not success:
            msg = f"Touch ID denied for: {action}"
            if error_msg:
                msg += f" ({error_msg})"
            raise AuthDeniedError(msg)

        return result

    def check_available(self) -> tuple[bool, str]:
        """
        Check whether Touch ID is available without prompting the user.
        Returns (available: bool, human_readable_status: str).
        Safe to call at dashboard startup for a status indicator.
        """
        if not _LA_AVAILABLE:
            return False, "pyobjc-framework-LocalAuthentication not installed"
        ctx = LAContext.new()
        can_eval, err = ctx.canEvaluatePolicy_error_(
            LAPolicyDeviceOwnerAuthenticationWithBiometrics, None
        )
        if can_eval:
            return True, "Touch ID available"
        return False, str(err) if err else "Touch ID unavailable"

    def audit_log_path(self) -> Path:
        """Return the path of the audit log file."""
        return _AUDIT_LOG
