from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
Network = Literal["auto", "solana", "evm"]


class ConfigurationError(ValueError):
    """Raised when required configuration is absent or unsafe."""


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} deve ser true ou false.")


def _normalize_chat(value: str) -> str:
    value = value.strip().rstrip("/")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    if value and not value.startswith("@") and not value.lstrip("-").isdigit():
        value = f"@{value}"
    return value


def _resolve_local_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True, slots=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str | None
    expected_account_username: str | None
    destination_chat: str
    source_chats: tuple[str, ...]
    allow_any_private_source: bool
    contract_network: Network
    dry_run: bool
    beep_enabled: bool
    beep_frequency_hz: int
    beep_duration_ms: int
    beep_repeat: int
    beep_gap_ms: int
    session_path: Path
    state_db: Path
    log_level: str

    def safe_summary(self) -> str:
        sources = ", ".join(self.source_chats) or "qualquer conversa privada"
        account = (
            f"@{self.expected_account_username}"
            if self.expected_account_username
            else "nao fixada"
        )
        return (
            f"conta={account}; destino={self.destination_chat}; "
            f"origens={sources}; rede={self.contract_network}; dry_run={self.dry_run}; "
            f"beep={self.beep_enabled}"
        )


def _parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve ser um numero inteiro.") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} deve ficar entre {minimum} e {maximum}.")
    return value


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ConfigurationError("TELEGRAM_API_ID deve ser um numero inteiro.") from exc
    if api_id <= 0:
        raise ConfigurationError("TELEGRAM_API_ID deve ser maior que zero.")

    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise ConfigurationError("TELEGRAM_API_HASH deve conter 32 caracteres hexadecimais.")

    expected_username = (
        os.getenv("EXPECTED_ACCOUNT_USERNAME", "").strip().lstrip("@").lower() or None
    )

    destination = _normalize_chat(os.getenv("DESTINATION_CHAT", "@helenus_trojanbot"))
    if not destination:
        raise ConfigurationError("DESTINATION_CHAT nao pode ficar vazio.")

    source_chats = tuple(
        normalized
        for item in os.getenv("SOURCE_CHATS", "").split(",")
        if (normalized := _normalize_chat(item))
    )
    allow_any_private = _parse_bool("ALLOW_ANY_PRIVATE_SOURCE", False)
    if not source_chats and not allow_any_private:
        raise ConfigurationError(
            "Defina SOURCE_CHATS ou habilite ALLOW_ANY_PRIVATE_SOURCE=true."
        )

    network = os.getenv("CONTRACT_NETWORK", "auto").strip().lower()
    if network not in {"auto", "solana", "evm"}:
        raise ConfigurationError("CONTRACT_NETWORK deve ser auto, solana ou evm.")

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("LOG_LEVEL invalido.")

    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        phone=os.getenv("TELEGRAM_PHONE", "").strip() or None,
        expected_account_username=expected_username,
        destination_chat=destination,
        source_chats=source_chats,
        allow_any_private_source=allow_any_private,
        contract_network=network,  # type: ignore[arg-type]
        dry_run=_parse_bool("DRY_RUN", True),
        beep_enabled=_parse_bool("BEEP_ENABLED", True),
        beep_frequency_hz=_parse_int("BEEP_FREQUENCY_HZ", 888, 37, 32_767),
        beep_duration_ms=_parse_int("BEEP_DURATION_MS", 8_000, 1, 60_000),
        beep_repeat=_parse_int("BEEP_REPEAT", 8, 1, 100),
        beep_gap_ms=_parse_int("BEEP_GAP_MS", 250, 0, 60_000),
        session_path=_resolve_local_path(os.getenv("TELEGRAM_SESSION", ".data/kenjihl")),
        state_db=_resolve_local_path(os.getenv("STATE_DB", ".data/forwarder.sqlite3")),
        log_level=log_level,
    )
