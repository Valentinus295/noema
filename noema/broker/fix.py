"""FIX Protocol Stub — FIX 4.4 session management (stub for future integration).

This is NOT a full FIX engine. It provides:
- FIX 4.4 session lifecycle (logon / heartbeat / logout)
- NewOrderSingle (35=D) message builder
- ExecutionReport (35=8) parser
- Tag-value encoding/decoding
- Enough protocol scaffolding to integrate with institutional liquidity providers
  or prime brokers when needed, without pulling in QuickFIX or similar heavy deps.

Target: future integration with institutional LPs, prime brokers, ECNs.
Current status: STUB — builds valid FIX messages but does NOT connect to a real
FIX counterparty. Use as a foundation for future FIX gateway development.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# FIX 4.4 Constants
# ═══════════════════════════════════════════════════════════

FIX_VERSION = "FIX.4.4"
FIX_DELIMITER = "\x01"  # SOH character (ASCII 0x01)
FIX_BEGIN_STRING = "8"
FIX_BODY_LENGTH = "9"
FIX_MSG_TYPE = "35"
FIX_SENDER_COMP_ID = "49"
FIX_TARGET_COMP_ID = "56"
FIX_MSG_SEQ_NUM = "34"
FIX_SENDING_TIME = "52"
FIX_CHECKSUM = "10"

# Session-level message types
MSG_HEARTBEAT = "0"
MSG_TEST_REQUEST = "1"
MSG_RESEND_REQUEST = "2"
MSG_REJECT = "3"
MSG_SEQUENCE_RESET = "4"
MSG_LOGOUT = "5"
MSG_LOGON = "A"

# Application-level message types
MSG_NEW_ORDER_SINGLE = "D"
MSG_EXECUTION_REPORT = "8"
MSG_ORDER_CANCEL_REQUEST = "F"
MSG_ORDER_CANCEL_REJECT = "9"
MSG_ORDER_STATUS_REQUEST = "H"

# Fields (tag numbers)
TAG_ACCOUNT = 1
TAG_ADV_TRANS_TYPE = 5
TAG_AVG_PX = 6
TAG_BEGIN_STRING = 8
TAG_BODY_LENGTH = 9
TAG_CHECKSUM = 10
TAG_CLORD_ID = 11
TAG_COMMISSION = 12
TAG_COMM_TYPE = 13
TAG_CURRENCY = 15
TAG_EXEC_ID = 17
TAG_EXEC_TRANS_TYPE = 20
TAG_HANDL_INST = 21
TAG_SECURITY_ID_SOURCE = 22
TAG_IOI_ID = 23
TAG_MSG_SEQ_NUM = 34
TAG_MSG_TYPE = 35
TAG_ORDER_ID = 37
TAG_ORDER_QTY = 38
TAG_ORDER_STATUS = 39
TAG_ORD_TYPE = 40
TAG_ORIG_CLORD_ID = 41
TAG_PRICE = 44
TAG_RULE80A = 47
TAG_SECURITY_ID = 48
TAG_SENDER_COMP_ID = 49
TAG_SENDER_SUB_ID = 50
TAG_SENDING_TIME = 52
TAG_SIDE = 54
TAG_SYMBOL = 55
TAG_TARGET_COMP_ID = 56
TAG_TEXT = 58
TAG_TIME_IN_FORCE = 59
TAG_TRANSACT_TIME = 60
TAG_ENCRYPT_METHOD = 98
TAG_HEART_BT_INT = 108
TAG_TEST_REQ_ID = 112
TAG_EXPIRE_TIME = 126
TAG_RESET_SEQ_NUM_FLAG = 141
TAG_EXEC_TYPE = 150
TAG_LEAVES_QTY = 151
TAG_CASH_ORDER_QTY = 152
TAG_ORDER_QTY2 = 192
TAG_FUTURES_SETT_DATE = 193
TAG_MATURITY_MONTH_YEAR = 200
TAG_PUT_OR_CALL = 201
TAG_STRIKE_PRICE = 202
TAG_SECURITY_TYPE = 167

# Side values
SIDE_BUY = "1"
SIDE_SELL = "2"
SIDE_BUY_MINUS = "3"
SIDE_SELL_PLUS = "4"
SIDE_SELL_SHORT = "5"

# Order types
ORD_TYPE_MARKET = "1"
ORD_TYPE_LIMIT = "2"
ORD_TYPE_STOP = "3"
ORD_TYPE_STOP_LIMIT = "4"

# Time in force
TIF_DAY = "0"
TIF_GTC = "1"
TIF_IOC = "3"
TIF_FOK = "4"

# Order status
ORD_STATUS_NEW = "0"
ORD_STATUS_PARTIALLY_FILLED = "1"
ORD_STATUS_FILLED = "2"
ORD_STATUS_DONE_FOR_DAY = "3"
ORD_STATUS_CANCELED = "4"
ORD_STATUS_REPLACED = "5"
ORD_STATUS_PENDING_CANCEL = "6"
ORD_STATUS_STOPPED = "7"
ORD_STATUS_REJECTED = "8"

# Exec types
EXEC_TYPE_NEW = "0"
EXEC_TYPE_PARTIAL_FILL = "1"
EXEC_TYPE_FILL = "2"
EXEC_TYPE_DONE_FOR_DAY = "3"
EXEC_TYPE_CANCELED = "4"
EXEC_TYPE_REPLACE = "5"
EXEC_TYPE_REJECTED = "8"
EXEC_TYPE_TRADE = "F"

# HandlInst
HANDL_INST_AUTO_PRIVATE = "1"
HANDL_INST_AUTO_PUBLIC = "2"

# EncryptMethod
ENCRYPT_METHOD_NONE = "0"


# ═══════════════════════════════════════════════════════════
# FIX Message Builder / Parser
# ═══════════════════════════════════════════════════════════

@dataclass
class FIXMessage:
    """A decoded FIX message (tag=value pairs)."""
    tags: dict[int, str] = field(default_factory=dict)
    raw: str = ""

    def get(self, tag: int, default: str = "") -> str:
        return self.tags.get(tag, default)

    def __str__(self) -> str:
        return self.encode()

    def encode(self) -> str:
        """Encode to wire-format FIX string with SOH delimiters."""
        # Sort tags for consistent output (BeginString, BodyLength, MsgType, ...)
        critical_tags = [
            TAG_BEGIN_STRING, TAG_BODY_LENGTH, TAG_MSG_TYPE,
            TAG_SENDER_COMP_ID, TAG_TARGET_COMP_ID, TAG_MSG_SEQ_NUM,
            TAG_SENDING_TIME,
        ]
        other_tags = sorted(set(self.tags) - set(critical_tags))

        # Build header + body
        parts: list[str] = []
        for tag in critical_tags:
            if tag in self.tags:
                parts.append(f"{tag}={self.tags[tag]}{FIX_DELIMITER}")
        for tag in other_tags:
            parts.append(f"{tag}={self.tags[tag]}{FIX_DELIMITER}")

        # Body length = length of everything after BodyLength(9) tag
        # Rebuild without BodyLength and Checksum for length calc
        body_parts = []
        for tag in critical_tags + other_tags:
            if tag in self.tags and tag not in (TAG_BODY_LENGTH, TAG_CHECKSUM):
                body_parts.append(f"{tag}={self.tags[tag]}{FIX_DELIMITER}")
        body_str = "".join(body_parts)
        self.tags[TAG_BODY_LENGTH] = str(len(body_str))

        # Rebuild with correct BodyLength
        final_parts: list[str] = []
        for tag in critical_tags:
            if tag in self.tags:
                final_parts.append(f"{tag}={self.tags[tag]}{FIX_DELIMITER}")
        for tag in other_tags:
            final_parts.append(f"{tag}={self.tags[tag]}{FIX_DELIMITER}")

        # Remove any existing Checksum before calculating
        msg_no_checksum = "".join(final_parts)
        checksum = _compute_checksum(msg_no_checksum)
        final_parts.append(f"10={checksum:03d}{FIX_DELIMITER}")

        return "".join(final_parts)


def _compute_checksum(msg: str) -> int:
    """FIX checksum: sum of all bytes modulo 256."""
    return sum(ord(c) for c in msg if c != FIX_DELIMITER) % 256


def parse_fix_message(raw: str) -> FIXMessage:
    """Parse a wire-format FIX string into a FIXMessage."""
    msg = FIXMessage(raw=raw)
    pairs = raw.split(FIX_DELIMITER)
    for pair in pairs:
        if "=" in pair:
            tag_str, value = pair.split("=", 1)
            try:
                tag = int(tag_str)
                msg.tags[tag] = value
            except ValueError:
                pass
    return msg


# ═══════════════════════════════════════════════════════════
# FIX Session
# ═══════════════════════════════════════════════════════════

class SessionState(str, enum.Enum):
    """FIX session state machine states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    LOGON_SENT = "logon_sent"
    LOGGED_ON = "logged_on"
    LOGOUT_SENT = "logout_sent"
    DISCONNECTED_GRACEFULLY = "disconnected_gracefully"


@dataclass
class FIXSessionConfig:
    """Configuration for a FIX 4.4 session."""
    sender_comp_id: str = "NOEMA"
    target_comp_id: str = "BROKER"
    heartbeat_interval: int = 30  # seconds
    username: str = ""
    password: str = ""
    account: str = ""
    host: str = "localhost"
    port: int = 9880
    reset_seq_on_logon: bool = True
    encrypt_method: str = ENCRYPT_METHOD_NONE


class FIXSession:
    """FIX 4.4 session manager (stub — no actual socket I/O).

    Manages the FIX session lifecycle:
    1. Logon (35=A) — authenticate with counterparty
    2. Heartbeat (35=0) — keepalive at configured interval
    3. Test Request (35=1) — respond to counterparty heartbeats
    4. Logout (35=5) — graceful disconnect
    5. Resend Request (35=2) — gap recovery

    This is a PROTOCOL STUB. It builds valid FIX messages but does NOT
    connect to a real FIX endpoint. Use as the foundation layer for a
    future async FIX gateway.
    """

    def __init__(self, config: FIXSessionConfig | None = None) -> None:
        self.config = config or FIXSessionConfig()
        self._state = SessionState.DISCONNECTED
        self._seq_num_in: int = 1
        self._seq_num_out: int = 1
        self._last_sent: float = 0.0
        self._last_received: float = 0.0
        self._session_start: float = 0.0
        self._logger = logger.bind(
            sender=self.config.sender_comp_id,
            target=self.config.target_comp_id,
        )

    # ── State ────────────────────────────────────────────────

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_logged_on(self) -> bool:
        return self._state == SessionState.LOGGED_ON

    @property
    def seq_num_out(self) -> int:
        return self._seq_num_out

    @property
    def seq_num_in(self) -> int:
        return self._seq_num_in

    # ── Session Lifecycle ────────────────────────────────────

    def logon(self, reset_seq: bool | None = None) -> FIXMessage:
        """Build a Logon (35=A) message.

        FIX 4.4 Logon required fields:
            8=BEGIN_STRING, 9=BODY_LENGTH, 35=A, 49=SENDER, 56=TARGET,
            34=SEQ_NUM, 52=SENDING_TIME, 98=ENCRYPT_METHOD, 108=HEART_BT_INT
        """
        if reset_seq is None:
            reset_seq = self.config.reset_seq_on_logon
        if reset_seq:
            self._seq_num_out = 1
            self._seq_num_in = 1

        msg = FIXMessage(tags={
            TAG_BEGIN_STRING: FIX_VERSION,
            TAG_MSG_TYPE: MSG_LOGON,
            TAG_SENDER_COMP_ID: self.config.sender_comp_id,
            TAG_TARGET_COMP_ID: self.config.target_comp_id,
            TAG_MSG_SEQ_NUM: str(self._seq_num_out),
            TAG_SENDING_TIME: _utc_timestamp(),
            TAG_ENCRYPT_METHOD: self.config.encrypt_method,
            TAG_HEART_BT_INT: str(self.config.heartbeat_interval),
        })

        if self.config.username:
            msg.tags[553] = self.config.username  # Username
        if self.config.password:
            msg.tags[554] = self.config.password  # Password
        if reset_seq:
            msg.tags[TAG_RESET_SEQ_NUM_FLAG] = "Y"

        self._state = SessionState.LOGON_SENT
        self._last_sent = time.monotonic()
        self._session_start = time.monotonic()
        self._logger.info("fix_logon_built", seq_num=self._seq_num_out)

        encoded = msg.encode()
        self._seq_num_out += 1
        return parse_fix_message(encoded)

    def handle_logon_response(self, msg: FIXMessage) -> bool:
        """Process a Logon response from counterparty."""
        if msg.get(TAG_MSG_TYPE) != MSG_LOGON:
            self._logger.error("unexpected_msg_type_on_logon", msg_type=msg.get(TAG_MSG_TYPE))
            return False

        self._seq_num_in = int(msg.get(TAG_MSG_SEQ_NUM, "1"))
        self._state = SessionState.LOGGED_ON
        self._last_received = time.monotonic()
        self._logger.info("fix_logon_accepted", counterparty_seq=self._seq_num_in)
        return True

    def heartbeat(self) -> FIXMessage:
        """Build a Heartbeat (35=0) message."""
        msg = FIXMessage(tags={
            TAG_BEGIN_STRING: FIX_VERSION,
            TAG_MSG_TYPE: MSG_HEARTBEAT,
            TAG_SENDER_COMP_ID: self.config.sender_comp_id,
            TAG_TARGET_COMP_ID: self.config.target_comp_id,
            TAG_MSG_SEQ_NUM: str(self._seq_num_out),
            TAG_SENDING_TIME: _utc_timestamp(),
        })

        self._last_sent = time.monotonic()
        encoded = msg.encode()
        self._seq_num_out += 1
        return parse_fix_message(encoded)

    def test_request(self, test_req_id: str = "") -> FIXMessage:
        """Build a Test Request (35=1) message."""
        if not test_req_id:
            test_req_id = f"TEST-{int(time.time() * 1000)}"

        msg = FIXMessage(tags={
            TAG_BEGIN_STRING: FIX_VERSION,
            TAG_MSG_TYPE: MSG_TEST_REQUEST,
            TAG_SENDER_COMP_ID: self.config.sender_comp_id,
            TAG_TARGET_COMP_ID: self.config.target_comp_id,
            TAG_MSG_SEQ_NUM: str(self._seq_num_out),
            TAG_SENDING_TIME: _utc_timestamp(),
            TAG_TEST_REQ_ID: test_req_id,
        })

        self._last_sent = time.monotonic()
        encoded = msg.encode()
        self._seq_num_out += 1
        return parse_fix_message(encoded)

    def logout(self, reason: str = "") -> FIXMessage:
        """Build a Logout (35=5) message."""
        tags = {
            TAG_BEGIN_STRING: FIX_VERSION,
            TAG_MSG_TYPE: MSG_LOGOUT,
            TAG_SENDER_COMP_ID: self.config.sender_comp_id,
            TAG_TARGET_COMP_ID: self.config.target_comp_id,
            TAG_MSG_SEQ_NUM: str(self._seq_num_out),
            TAG_SENDING_TIME: _utc_timestamp(),
        }
        if reason:
            tags[TAG_TEXT] = reason

        msg = FIXMessage(tags=tags)
        self._state = SessionState.LOGOUT_SENT
        self._last_sent = time.monotonic()
        self._logger.info("fix_logout_built", reason=reason)

        encoded = msg.encode()
        self._seq_num_out += 1
        return parse_fix_message(encoded)

    def handle_logout_response(self, msg: FIXMessage) -> None:
        """Process a Logout response."""
        self._state = SessionState.DISCONNECTED_GRACEFULLY
        self._last_received = time.monotonic()
        self._logger.info("fix_logout_complete",
                          text=msg.get(TAG_TEXT, ""))

    def resend_request(self, start_seq: int, end_seq: int = 0) -> FIXMessage:
        """Build a Resend Request (35=2) for gap recovery."""
        msg = FIXMessage(tags={
            TAG_BEGIN_STRING: FIX_VERSION,
            TAG_MSG_TYPE: MSG_RESEND_REQUEST,
            TAG_SENDER_COMP_ID: self.config.sender_comp_id,
            TAG_TARGET_COMP_ID: self.config.target_comp_id,
            TAG_MSG_SEQ_NUM: str(self._seq_num_out),
            TAG_SENDING_TIME: _utc_timestamp(),
            7: str(start_seq),   # BeginSeqNo
        })
        if end_seq > 0:
            msg.tags[16] = str(end_seq)  # EndSeqNo
        else:
            msg.tags[16] = "0"  # 0 = infinity

        self._last_sent = time.monotonic()
        encoded = msg.encode()
        self._seq_num_out += 1
        return parse_fix_message(encoded)

    # ── Session helpers ──────────────────────────────────────

    def needs_heartbeat(self) -> bool:
        """Check if heartbeat is due based on configured interval."""
        if self._state != SessionState.LOGGED_ON:
            return False
        elapsed = time.monotonic() - self._last_sent
        return elapsed >= self.config.heartbeat_interval

    def heartbeat_missed(self) -> bool:
        """Check if counterparty is silent (no msg received within 2x heartbeat)."""
        if self._state != SessionState.LOGGED_ON:
            return False
        elapsed = time.monotonic() - self._last_received
        return elapsed >= (self.config.heartbeat_interval * 2)

    def receive(self, raw_msg: str) -> FIXMessage:
        """Process an incoming FIX message, updating sequence numbers."""
        msg = parse_fix_message(raw_msg)
        self._last_received = time.monotonic()

        incoming_seq = int(msg.get(TAG_MSG_SEQ_NUM, "0"))
        if incoming_seq > 0:
            expected = self._seq_num_in
            if incoming_seq != expected:
                self._logger.warning(
                    "fix_gap_detected",
                    expected=expected,
                    received=incoming_seq,
                )
            self._seq_num_in = incoming_seq + 1

        msg_type = msg.get(TAG_MSG_TYPE)
        if msg_type == MSG_LOGON:
            self.handle_logon_response(msg)
        elif msg_type == MSG_LOGOUT:
            self.handle_logout_response(msg)

        return msg

    def disconnect(self) -> None:
        """Force disconnect the session (without graceful logout)."""
        self._state = SessionState.DISCONNECTED
        self._logger.info("fix_session_disconnected")

    def reset(self) -> None:
        """Full reset of session state."""
        self._state = SessionState.DISCONNECTED
        self._seq_num_in = 1
        self._seq_num_out = 1
        self._last_sent = 0.0
        self._last_received = 0.0
        self._session_start = 0.0


# ═══════════════════════════════════════════════════════════
# Application Messages
# ═══════════════════════════════════════════════════════════

@dataclass
class NewOrderSingle:
    """FIX NewOrderSingle (35=D) parameters.

    Maps forex/mt5 concepts to FIX 4.4 fields.
    """
    symbol: str                           # 55
    side: str                             # 54 — 1=Buy, 2=Sell
    order_qty: float = 0.01              # 38 — lot size
    ord_type: str = ORD_TYPE_MARKET      # 40 — 1=Market, 2=Limit
    price: float = 0.0                   # 44 — limit price (0 for market)
    time_in_force: str = TIF_IOC         # 59
    cl_ord_id: str = ""                  # 11 — client order ID
    account: str = ""                    # 1
    currency: str = ""                   # 15
    stop_px: float = 0.0                 # 99 — stop price
    handl_inst: str = HANDL_INST_AUTO_PRIVATE  # 21


def build_new_order_single(
    session: FIXSession,
    order: NewOrderSingle,
) -> FIXMessage:
    """Build a FIX 4.4 NewOrderSingle (35=D) message.

    Required fields per FIX 4.4 spec:
        8, 9, 35, 49, 56, 34, 52, 11, 21, 55, 54, 38, 40, 59
    """
    if not order.cl_ord_id:
        order.cl_ord_id = f"NOEMA-{int(time.time() * 1000)}-{session.seq_num_out}"

    tags: dict[int, str] = {
        TAG_BEGIN_STRING: FIX_VERSION,
        TAG_MSG_TYPE: MSG_NEW_ORDER_SINGLE,
        TAG_SENDER_COMP_ID: session.config.sender_comp_id,
        TAG_TARGET_COMP_ID: session.config.target_comp_id,
        TAG_MSG_SEQ_NUM: str(session.seq_num_out),
        TAG_SENDING_TIME: _utc_timestamp(),
        TAG_CLORD_ID: order.cl_ord_id,
        TAG_HANDL_INST: order.handl_inst,
        TAG_SYMBOL: order.symbol,
        TAG_SIDE: order.side,
        TAG_ORDER_QTY: str(order.order_qty),
        TAG_ORD_TYPE: order.ord_type,
        TAG_TIME_IN_FORCE: order.time_in_force,
    }

    if order.price > 0:
        tags[TAG_PRICE] = str(order.price)
    if order.account:
        tags[TAG_ACCOUNT] = order.account
    if order.currency:
        tags[TAG_CURRENCY] = order.currency
    if order.stop_px > 0:
        tags[99] = str(order.stop_px)

    if session.config.account:
        tags.setdefault(TAG_ACCOUNT, session.config.account)

    msg = FIXMessage(tags=tags)
    session._last_sent = time.monotonic()
    encoded = msg.encode()
    # Return a fresh parse so seq and timing are right
    return parse_fix_message(encoded)


# ═══════════════════════════════════════════════════════════
# Execution Report Parser
# ═══════════════════════════════════════════════════════════

@dataclass
class ExecutionReport:
    """Parsed FIX 4.4 ExecutionReport (35=8)."""
    # Core
    order_id: str = ""                  # 37
    exec_id: str = ""                   # 17
    exec_type: str = ""                 # 150 — 0=New, 1=Partial, 2=Fill
    ord_status: str = ""                # 39 — 0=New, 2=Filled, 4=Canceled
    symbol: str = ""                    # 55
    side: str = ""                      # 54
    order_qty: float = 0.0              # 38
    cum_qty: float = 0.0                # 14 — cumulative filled qty
    leaves_qty: float = 0.0             # 151
    last_qty: float = 0.0               # 32 — last fill qty
    last_px: float = 0.0                # 31 — last fill price
    avg_px: float = 0.0                 # 6
    price: float = 0.0                  # 44 — limit price
    transact_time: str = ""             # 60
    cl_ord_id: str = ""                 # 11
    text: str = ""                      # 58
    currency: str = ""                  # 15

    # Derived
    is_fill: bool = False
    is_partial: bool = False
    is_rejected: bool = False
    is_canceled: bool = False
    raw: str = ""


def parse_execution_report(msg: FIXMessage | str) -> ExecutionReport:
    """Parse a FIX 4.4 ExecutionReport (35=8) message.

    Handles both raw wire-format string and pre-parsed FIXMessage.
    """
    if isinstance(msg, str):
        msg = parse_fix_message(msg)

    exec_type = msg.get(150, "")
    ord_status = msg.get(TAG_ORDER_STATUS, "")

    report = ExecutionReport(
        order_id=msg.get(TAG_ORDER_ID, ""),
        exec_id=msg.get(TAG_EXEC_ID, ""),
        exec_type=exec_type,
        ord_status=ord_status,
        symbol=msg.get(TAG_SYMBOL, ""),
        side=msg.get(TAG_SIDE, ""),
        order_qty=_parse_float(msg.get(TAG_ORDER_QTY, "0")),
        cum_qty=_parse_float(msg.get(14, "0")),
        leaves_qty=_parse_float(msg.get(TAG_LEAVES_QTY, "0")),
        last_qty=_parse_float(msg.get(32, "0")),
        last_px=_parse_float(msg.get(31, "0")),
        avg_px=_parse_float(msg.get(TAG_AVG_PX, "0")),
        price=_parse_float(msg.get(TAG_PRICE, "0")),
        transact_time=msg.get(TAG_TRANSACT_TIME, ""),
        cl_ord_id=msg.get(TAG_CLORD_ID, ""),
        text=msg.get(TAG_TEXT, ""),
        currency=msg.get(TAG_CURRENCY, ""),
        raw=msg.raw,
    )

    # Derived flags
    report.is_fill = exec_type in (EXEC_TYPE_FILL, EXEC_TYPE_TRADE)
    report.is_partial = exec_type == EXEC_TYPE_PARTIAL_FILL
    report.is_rejected = exec_type == EXEC_TYPE_REJECTED or ord_status == ORD_STATUS_REJECTED
    report.is_canceled = exec_type == EXEC_TYPE_CANCELED or ord_status == ORD_STATUS_CANCELED

    return report


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _utc_timestamp() -> str:
    """FIX UTCTimestamp format: YYYYMMDD-HH:MM:SS.sss"""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S.") + \
           f"{datetime.now(timezone.utc).microsecond // 1000:03d}"


def _parse_float(s: str) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def validate_checksum(msg: FIXMessage) -> bool:
    """Validate FIX message checksum."""
    if TAG_CHECKSUM not in msg.tags:
        return False
    # Rebuild message without checksum
    # Remove checksum tag from raw
    raw = msg.raw
    checksum_pos = raw.rfind("10=")
    if checksum_pos < 0:
        return False
    body = raw[:checksum_pos]
    expected = _compute_checksum(body)
    actual = int(msg.tags[TAG_CHECKSUM])
    return expected == actual
