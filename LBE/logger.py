from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
import json
import sys

from .types import Error


# Log Levels
TRACE = 0
DEBUG = 1
INFO = 2
WARN = 3
ERROR = 4
FATAL = 5

LEVEL_NAMES = {
    TRACE: "TRACE",
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARN: "WARN",
    ERROR: "ERROR",
    FATAL: "FATAL",
}


@dataclass(slots=True)
class LogRecord:
    level: int
    message: str
    channel: str = "kernel"
    timestamp: datetime = field(default_factory=datetime.now)
    data: Any = None
    error: Error | None = None
    entity_id: Any = None       # e.g., RuntimeID or StorageID hex
    action: str | None = None   # e.g., 'created', 'mutated', 'saved', 'loaded', 'reloaded'
    before: Any = None          # state/value before mutation
    after: Any = None           # state/value after mutation


class Logger:
    def __init__(
        self,
        min_level: int = INFO,
        channel_filter: set[str] | None = None,
        auto_pretty_print: bool = True,
        max_records: int = 1000,
    ):
        self.min_level = min_level
        self.channel_filter = channel_filter  # If set, only print records from these channels
        self.auto_pretty_print = auto_pretty_print
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self.max_records = max_records
        self.records: list[LogRecord] = []

    def is_enabled(self, level: int, channel: str = "kernel") -> bool:
        return level >= self.min_level and (self.channel_filter is None or channel in self.channel_filter)

    def set_min_level(self, level: int) -> None:
        """Set minimum level to output to console."""
        self.min_level = level

    def set_channels(self, *channels: str) -> None:
        """Filter console output to specific channels only."""
        self.channel_filter = set(channels) if channels else None

    def log(
        self,
        level: int,
        message: str,
        channel: str = "kernel",
        data: Any = None,
        error: Error | None = None,
        entity_id: Any = None,
        action: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> LogRecord:
        """Store enabled records in a bounded history and optionally print them."""
        if not self.is_enabled(level, channel):
            return None
        record = LogRecord(
            level=level,
            message=message,
            channel=channel,
            data=data,
            error=error,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
        )
        self.records.append(record)
        if len(self.records) > self.max_records:
            del self.records[:len(self.records) - self.max_records]

        # Apply print filters
        if level >= self.min_level:
            if self.channel_filter is None or channel in self.channel_filter:
                if self.auto_pretty_print:
                    self.pretty_print(record)
                else:
                    print(f"[{record.timestamp.strftime('%H:%M:%S')}] [{LEVEL_NAMES.get(level, str(level))}] [{channel}] {message}")

        return record

    def trace(
        self,
        message: str,
        channel: str = "kernel",
        data: Any = None,
        error: Exception | None = None,
        entity_id: Any = None,
        action: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> LogRecord:
        return self.log(
            TRACE,
            message,
            channel,
            data=data,
            error=error,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
        )

    def debug(
        self,
        message: str,
        channel: str = "kernel",
        data: Any = None,
        error: Exception | None = None,
        entity_id: Any = None,
        action: str | None = None,
    ) -> LogRecord:
        return self.log(DEBUG, message, channel, data=data, error=error, entity_id=entity_id, action=action)

    def info(
        self,
        message: str,
        channel: str = "kernel",
        data: Any = None,
        error: Exception | None = None,
        entity_id: Any = None,
        action: str | None = None,
    ) -> LogRecord:
        return self.log(INFO, message, channel, data=data, error=error, entity_id=entity_id, action=action)

    def warn(
        self,
        message: str,
        channel: str = "kernel",
        data: Any = None,
        error: Exception | None = None,
        entity_id: Any = None,
    ) -> LogRecord:
        return self.log(WARN, message, channel, data=data, error=error, entity_id=entity_id)

    def error(
        self,
        message: str,
        channel: str = "kernel",
        error: Error | None = None,
        data: Any = None,
        entity_id: Any = None,
    ) -> LogRecord:
        return self.log(ERROR, message, channel, data=data, error=error, entity_id=entity_id)

    def fatal(
        self,
        message: str,
        channel: str = "kernel",
        error: Error | None = None,
        data: Any = None,
        entity_id: Any = None,
    ) -> LogRecord:
        return self.log(FATAL, message, channel, data=data, error=error, entity_id=entity_id)

    def get_history(self, entity_id: Any) -> list[LogRecord]:
        """Retrieve complete chronological trace history for a specific resource/entity."""
        return [r for r in self.records if r.entity_id == entity_id]

    def print_history(self, entity_id: Any) -> None:
        """Pretty-print the full provenance / timeline of an entity."""
        history = self.get_history(entity_id)
        RESET = "\033[0m"
        BOLD = "\033[1m"
        CYAN = "\033[96m"
        GRAY = "\033[90m"
        YELLOW = "\033[93m"

        print(f"\n{CYAN}=== Provenance History for Target [{entity_id}] ({len(history)} events) ==={RESET}")
        if not history:
            print(f"  {GRAY}(No trace records recorded){RESET}\n")
            return

        for idx, rec in enumerate(history, 1):
            time_str = rec.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            action_tag = f"[{rec.action.upper()}] " if rec.action else ""
            print(f" {GRAY}{idx:02d}.{RESET} [{time_str}] {YELLOW}{action_tag}{RESET}{rec.message}")
            if rec.before is not None or rec.after is not None:
                if rec.before is not None:
                    print(f"      {GRAY}Before:{RESET} {rec.before}")
                if rec.after is not None:
                    print(f"      {CYAN}After: {RESET} {rec.after}")
            if rec.data is not None:
                print(f"      {GRAY}Data:  {RESET} {rec.data}")
        print(f"{CYAN}{'=' * 60}{RESET}\n")

    def find(
        self,
        min_level: int | None = None,
        max_level: int | None = None,
        channel: str | None = None,
        query: str | None = None,
        error_code: int | None = None,
        predicate: Callable[[LogRecord], bool] | None = None,
    ) -> list[LogRecord]:
        """Search and filter stored logs in memory."""
        results: list[LogRecord] = []
        for r in self.records:
            if min_level is not None and r.level < min_level:
                continue
            if max_level is not None and r.level > max_level:
                continue
            if channel is not None and r.channel != channel:
                continue
            if query is not None and query.lower() not in r.message.lower():
                continue
            if error_code is not None:
                if r.error is None or r.error.code != error_code:
                    continue
            if predicate is not None and not predicate(r):
                continue
            results.append(r)
        return results

    def clear(self) -> None:
        """Clear log history."""
        self.records.clear()

    @staticmethod
    def pretty_print(record: LogRecord) -> None:
        """Format and print record with clean colors and structure."""
        level_styles = {
            TRACE: ("\033[90m", "TRACE"),
            DEBUG: ("\033[94m", "DEBUG"),
            INFO:  ("\033[92m", "INFO "),
            WARN:  ("\033[93m", "WARN "),
            ERROR: ("\033[91m", "ERROR"),
            FATAL: ("\033[1;91m", "FATAL"),
        }
        color, lvl_name = level_styles.get(record.level, ("\033[0m", "LOG  "))
        RESET = "\033[0m"
        BOLD = "\033[1m"
        GRAY = "\033[90m"
        CYAN = "\033[96m"

        time_str = record.timestamp.strftime("%H:%M:%S.%f")[:-3]

        if record.level in (ERROR, FATAL) and record.error is not None:
            # Boxed error format
            err = record.error
            code_names = {
                1: "StorageIDNotFoundOnMemoryError",
                2: "StorageIDNotFoundOnDiskError",
                3: "RuntimeIDNotFoundOnMemoryError",
                4: "RuntimeIDNotFoundOnDiskError",
                5: "FolderNotFoundOnDiskError",
                6: "FolderNotFoundOnMemoryError",
                7: "InvalidResourceDataError",
                8: "ResourceAlreadyExistsOnDiskError",
                9: "FailedToSaveResourceOnDiskError",
            }
            code_str = code_names.get(err.code, f"Code {err.code}")

            try:
                "┏━┃┠┗".encode(sys.stdout.encoding or "utf-8")
                top = f"{color}┏━━ [{lvl_name}] [{record.channel}] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}"
                mid = f"{color}┠──────────────────────────────────────────────────────────────────────────{RESET}"
                bot = f"{color}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}"
                bar = f"{color}┃{RESET}"
            except (UnicodeEncodeError, LookupError):
                top = f"{color}+--- [{lvl_name}] [{record.channel}] ---------------------------------------------------------{RESET}"
                mid = f"{color}+---------------------------------------------------------------------------{RESET}"
                bot = f"{color}+---------------------------------------------------------------------------{RESET}"
                bar = f"{color}|{RESET}"

            print(f"\n{top}")
            print(f"{bar} {GRAY}{time_str}{RESET} {BOLD}{record.message}{RESET}")
            print(f"{mid}")
            print(f"{bar} {BOLD}Error:{RESET} {err.message} {GRAY}[{code_str}]{RESET}")
            print(f"{bar} {BOLD}Description:{RESET} {err.description}")

            combined_data = {}
            if record.data is not None:
                combined_data["log_data"] = record.data
            if err.data is not None:
                combined_data["error_data"] = err.data

            if combined_data:
                print(f"{bar} {CYAN}Context Data:{RESET}")
                for k, val in combined_data.items():
                    if isinstance(val, dict):
                        # Format nested dicts cleanly
                        formatted = json.dumps(val, indent=2, default=lambda o: f"StorageID(0x{o.hex()})" if isinstance(o, bytes) and len(o) == 16 else str(o))
                        formatted = formatted.replace("\n", f"\n{bar}      ")
                        print(f"{bar}   * {BOLD}{k}{RESET}: {formatted}")
                    elif isinstance(val, bytes) and len(val) == 16:
                        print(f"{bar}   * {BOLD}{k}{RESET}: StorageID(0x{val.hex()})")
                    else:
                        print(f"{bar}   * {BOLD}{k}{RESET}: {val}")

            print(f"{bot}\n")
        else:
            # Inline pretty-print for trace/debug/info/warn
            print(f"{GRAY}[{time_str}]{RESET} {color}[{lvl_name}]{RESET} {GRAY}[{record.channel}]{RESET} {record.message}")
            if record.data is not None:
                if isinstance(record.data, dict):
                    formatted = json.dumps(record.data, indent=2, default=str).replace("\n", "\n  ")
                    print(f"  {CYAN}Data:{RESET} {formatted}")
                else:
                    print(f"  {CYAN}Data:{RESET} {record.data}")


# Default global engine logger instance
logger = Logger()
