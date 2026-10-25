from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    analyzer_model: str = os.getenv("ANALYZER_MODEL", "r1-tester")
    workhorse_model: str = os.getenv("WORKHORSE_MODEL", "qwen-tester")
    analyzer_num_ctx: int = int(os.getenv("ANALYZER_NUM_CTX", "8192"))
    workhorse_num_ctx: int = int(os.getenv("WORKHORSE_NUM_CTX", "4096"))
    max_file_chars: int = int(os.getenv("MAX_FILE_CHARS", "60000"))
    max_diff_lines: int = int(os.getenv("MAX_DIFF_LINES", "200"))
    max_files_touched: int = int(os.getenv("MAX_FILES_TOUCHED", "5"))
    max_fix_attempts: int = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15.0"))
    http_retries: int = int(os.getenv("HTTP_RETRIES", "1"))
    concurrency: int = int(os.getenv("CONCURRENCY", "4"))
    batch_size: int = int(os.getenv("BATCH_SIZE", "100"))
    verify_port_offset: int = int(os.getenv("VERIFY_PORT_OFFSET", "1000"))
    verify_startup_timeout: float = float(os.getenv("VERIFY_STARTUP_TIMEOUT", "20.0"))
    verify_timeout: float = float(os.getenv("VERIFY_TIMEOUT", "30.0"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./api_tester.db")
    audit_enabled: bool = os.getenv("AUDIT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    audit_max_chars: int = int(os.getenv("AUDIT_MAX_CHARS", "200000"))

    def __post_init__(self) -> None:
        positive = {
            "analyzer_num_ctx": self.analyzer_num_ctx,
            "workhorse_num_ctx": self.workhorse_num_ctx,
            "max_file_chars": self.max_file_chars,
            "max_diff_lines": self.max_diff_lines,
            "max_files_touched": self.max_files_touched,
            "max_fix_attempts": self.max_fix_attempts,
            "http_timeout": self.http_timeout,
            "concurrency": self.concurrency,
            "batch_size": self.batch_size,
            "verify_startup_timeout": self.verify_startup_timeout,
            "verify_timeout": self.verify_timeout,
            "audit_max_chars": self.audit_max_chars,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if self.http_retries < 0:
            invalid.append("http_retries")
        if invalid:
            raise ValueError(f"Settings must be positive: {', '.join(invalid)}")
        if self.verify_port_offset < 0:
            raise ValueError("verify_port_offset must be non-negative")

SETTINGS = Settings()
