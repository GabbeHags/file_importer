from multiprocessing.sharedctypes import Synchronized
import os
from queue import Empty
import argparse
import logging
import shutil
from pathlib import Path
from multiprocessing import Queue, Process, Value

from dataclasses import dataclass, field
from ctypes import c_int

# Configure logger
logger = logging.getLogger(__name__)

# Allowed characters for cleaned paths and filenames
# Keep only: Latin letters, numbers, dots, dashes, underscores, spaces, parentheses, brackets
ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ()[]{}"
)


def _clean_path(path: Path) -> Path:
    """Clean path by removing invalid characters from each component.

    Preserves whether the path is absolute or relative.
    """
    is_absolute = path.is_absolute()
    parts = []
    for part in path.parts:
        # Skip empty parts (like '/' on Unix paths)
        if not part or part == "/":
            continue
        cleaned = "".join(c for c in part if c in ALLOWED_CHARS)
        if cleaned:
            parts.append(cleaned)

    if not parts:
        return path  # Return original if no valid parts

    result = Path(*parts)
    # Restore absolute path if original was absolute
    if is_absolute:
        result = Path("/") / result
    return result


def _clean_filename(filename: str) -> str:
    """Remove non-standard characters from filename.

    Keep only: Latin letters, numbers, dots, dashes, underscores, spaces, parentheses, brackets.
    """
    cleaned = "".join(c for c in filename if c in ALLOWED_CHARS)
    return cleaned if cleaned else filename  # Return original if nothing valid remains


@dataclass(frozen=True)
class Config:
    """Global configuration for the hardlink copy operation."""

    sources: list[Path]
    destination: Path
    verbose: bool = False
    skip_extensions: list[str] = field(default_factory=list)
    dry_run: bool = False
    workers: int = 1
    debug: bool = False
    copy_strategy: str = "hardlink"  # "auto" (hardlink w/ copy fallback), "hardlink" (only), or "copy" (only)

    def __post_init__(self):
        """Normalize paths and skip extensions."""
        # Normalize sources list (keep original names with glyphs)
        normalized_sources = [Path(src).resolve() for src in self.sources]

        # Clean destination path only
        cleaned_destination = _clean_path(Path(self.destination).resolve())

        object.__setattr__(self, "sources", normalized_sources)
        object.__setattr__(self, "destination", cleaned_destination)
        # Ensure extensions start with a dot
        skip_exts = [
            ext if ext.startswith(".") else f".{ext}" for ext in self.skip_extensions
        ]
        object.__setattr__(self, "skip_extensions", skip_exts)


# Global config instance
config: Config | None = None


@dataclass(slots=True, frozen=True)
class FileToProcess:
    """Dataclass representing a file to be hardlinked."""

    src_path: Path
    dst_path: Path
    rel_path: Path


def _process_file(
    file_info: FileToProcess,
    dry_run: bool,
    verbose: bool,
    debug: bool,
    copy_strategy: str = "auto",
) -> int:
    """Helper function to process a single file for parallel execution."""
    try:
        if not dry_run:
            # Ensure parent directory exists
            file_info.dst_path.parent.mkdir(parents=True, exist_ok=True)

            if copy_strategy == "copy":
                # Only copy, never hardlink
                shutil.copy2(file_info.src_path, file_info.dst_path)
                link_type = "copied"
            elif copy_strategy == "hardlink":
                # Only hardlink, fail on cross-device
                os.link(file_info.src_path, file_info.dst_path)
                link_type = "hardlinked"
            else:  # copy_strategy == "auto"
                # Try hardlink first, fall back to copy
                try:
                    os.link(file_info.src_path, file_info.dst_path)
                    link_type = "hardlinked"
                except OSError as e:
                    if e.errno == 18:  # EXDEV: Invalid cross-device link
                        shutil.copy2(file_info.src_path, file_info.dst_path)
                        link_type = "copied (cross-device)"
                    else:
                        raise
        else:
            link_type = (
                f"{copy_strategy} (dry-run)"
                if copy_strategy != "auto"
                else "hardlinked (dry-run)"
            )

        if verbose:
            logger.info(f"{link_type.capitalize()}: {file_info.rel_path}")
        return 1
    except OSError as e:
        if debug:
            logger.exception(f"Error processing {file_info.rel_path}")
        else:
            logger.error(f"Error processing {file_info.rel_path}: {e}")
        return 0


def _producer(
    src_dir_queue: "Queue[SourceDirectory]",
    dirs_left_to_scan: "Synchronized[int]",
    skip_extensions: list[str],
    destination: Path,
    verbose: bool,
    queue: "Queue[FileToProcess]",
) -> None:
    """Producer: Scans a source directory and enqueues files to process."""

    while dirs_left_to_scan.value > 0:
        try:
            # Use timeout to avoid blocking indefinitely if queue is empty
            src_dir: SourceDirectory = src_dir_queue.get(timeout=0.1)
        except Empty:
            # Queue timeout, check if there's more work to do and continue
            continue

        for src_path in src_dir.sub_source.glob("*"):
            # Skip directories
            if src_path.is_dir():
                src_dir_queue.put(
                    SourceDirectory(source=src_dir.source, sub_source=src_path)
                )  # Enqueue subdirectory for further scanning
                with dirs_left_to_scan.get_lock():
                    dirs_left_to_scan.value += 1
                continue

            # Skip files that are under the destination directory
            try:
                src_path.relative_to(destination)
                if verbose:
                    rel_path = src_path.relative_to(src_dir.source)
                    logger.info(f"Skipped (in destination): {rel_path}")
                continue
            except ValueError:
                # File is not under destination, proceed normally
                pass

            # Skip files with extensions in skip list
            if src_path.suffix in skip_extensions:
                if verbose:
                    rel_path = src_path.relative_to(src_dir.source)
                    logger.info(f"Skipped (extension filtered): {rel_path}")
                continue

            # Calculate relative path from source root (keep source names with glyphs)
            rel_path = src_path.relative_to(src_dir.source)
            # Clean each component of the relative path for destination only
            cleaned_rel_parts = [_clean_filename(part) for part in rel_path.parts]
            cleaned_rel_path = Path(*cleaned_rel_parts)

            dst_path = destination / cleaned_rel_path

            # Skip if destination file already exists
            if dst_path.exists() or dst_path.is_symlink():
                if verbose:
                    logger.info(f"Skipped (already exists): {cleaned_rel_path}")
                continue

            # Enqueue the file for processing
            logger.debug(f"Producer enqueuing file: {src_path} -> {dst_path}")
            queue.put(
                FileToProcess(
                    src_path=src_path,
                    dst_path=dst_path,
                    rel_path=cleaned_rel_path,
                )
            )
        with dirs_left_to_scan.get_lock():
            dirs_left_to_scan.value -= 1


def _consumer(
    queue: "Queue[FileToProcess | None]",
    dry_run: bool,
    verbose: bool,
    debug: bool,
    file_count: "Synchronized[int]",
    copy_strategy: str = "auto",
) -> None:
    """Consumer: Dequeues files and processes them. Updates shared file_count."""
    while True:
        file_info = queue.get()
        if file_info is None:  # Sentinel value indicating end of work
            break
        logger.debug(f"Consumer got file to process: {file_info.src_path}")
        result = _process_file(file_info, dry_run, verbose, debug, copy_strategy)
        logger.debug(f"Consumer finished processing: {file_info.src_path}")
        if result == 1:
            with file_count.get_lock():
                file_count.value += 1


@dataclass(slots=True, frozen=True)
class SourceDirectory:
    """Dataclass representing a source directory to be scanned."""

    source: Path
    sub_source: Path


def hardlink_copy_recursive(cfg: Config) -> int:
    """Hardlink copy all files from src directories to dst, preserving directory structure.

    Uses a producer-consumer pattern where producers scan source directories
    and enqueue files, while consumers process and hardlink them.

    Args:
        cfg: Config object containing all operation parameters

    Returns:
        Number of files hardlinked
    """
    # Validate all sources
    for src in cfg.sources:
        if not src.exists():
            raise ValueError(f"Source directory does not exist: {src}")
        if not src.is_dir():
            raise ValueError(f"Source path is not a directory: {src}")

    # Create destination root if it doesn't exist (skip in dry run)
    if not cfg.dry_run:
        cfg.destination.mkdir(parents=True, exist_ok=True)

    # Create a queue for producer-consumer communication
    queue: "Queue[FileToProcess | None]" = Queue()

    # Create a shared counter for tracking processed files
    file_count = Value(c_int, 0)

    num_producers = max(1, cfg.workers // 2)
    num_consumers = max(1, cfg.workers // 2)

    # Start producer processes (one per source directory)
    producer_processes: list[Process] = []
    sources_queue: "Queue[SourceDirectory]" = Queue()
    dirs_left_to_scan = Value(c_int, 0)
    for src_dir in cfg.sources:
        sources_queue.put(SourceDirectory(source=src_dir, sub_source=src_dir))
        with dirs_left_to_scan.get_lock():
            dirs_left_to_scan.value += 1

    for _ in range(num_producers):
        p = Process(
            target=_producer,
            args=(
                sources_queue,
                dirs_left_to_scan,
                cfg.skip_extensions,
                cfg.destination,
                cfg.verbose,
                queue,
            ),
        )
        p.start()
        producer_processes.append(p)

    # Start consumer processes
    consumer_processes: list[Process] = []
    for _ in range(num_consumers):
        p = Process(
            target=_consumer_wrapper,
            args=(
                queue,
                cfg.dry_run,
                cfg.verbose,
                cfg.debug,
                file_count,
                cfg.copy_strategy,
            ),
        )
        p.start()
        consumer_processes.append(p)

    # Wait for all producers to finish
    for i, p in enumerate(producer_processes):
        logger.debug(f"Waiting for producer {i} to finish")
        p.join()
        logger.debug(f"Producer {i} finished")

    # Send sentinel values to signal consumers to stop
    for _ in range(num_consumers):
        queue.put(None)

    if not queue.empty():
        for _ in range(num_producers):
            p = Process(
                target=_consumer_wrapper,
                args=(
                    queue,
                    cfg.dry_run,
                    cfg.verbose,
                    cfg.debug,
                    file_count,
                    cfg.copy_strategy,
                ),
            )
            p.start()
            consumer_processes.append(p)

    for _ in range(num_producers):
        queue.put(None)

    # Wait for all consumers to finish
    for i, p in enumerate(consumer_processes):
        logger.debug(f"Waiting for consumer {i} to finish")
        p.join()
        logger.debug(f"Consumer {i} finished")

    return file_count.value


def _consumer_wrapper(
    queue: "Queue[FileToProcess | None]",
    dry_run: bool,
    verbose: bool,
    debug: bool,
    file_count: "Synchronized[int]",
    copy_strategy: str = "auto",
) -> None:
    """Wrapper function for consumer process to handle queue communication."""
    _consumer(queue, dry_run, verbose, debug, file_count, copy_strategy)


def _create_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Recursively hardlink copy all files from one or more source directories to a destination, preserving paths."
    )
    parser.add_argument(
        "sources", nargs="+", help="One or more source directories to copy from"
    )
    parser.add_argument("destination", help="Destination directory to copy to")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print progress information"
    )
    parser.add_argument(
        "-s",
        "--skip-extensions",
        nargs="+",
        default=[],
        help="File extensions to skip (e.g., .!qB .tmp)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the operation without creating hardlinks",
    )
    parser.add_argument(
        "-j",
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show full traceback on errors",
    )
    parser.add_argument(
        "--copy-strategy",
        choices=["auto", "hardlink", "copy"],
        default="hardlink",
        help="File copying strategy: auto (hardlink with copy fallback), hardlink (only), or copy (only). Default: hardlink",
    )
    return parser


def main():
    global config

    parser = _create_parser()

    args = parser.parse_args()

    # Configure logging based on verbose or debug flag
    log_level = logging.DEBUG if (args.verbose or args.debug) else logging.INFO
    log_format = (
        "%(asctime)s - %(levelname)s [%(filename)s:%(lineno)d]: %(message)s"
        if args.debug
        else "%(asctime)s - %(levelname)s: %(message)s"
    )
    logging.basicConfig(
        level=log_level,
        format=log_format,
    )

    if args.workers is None:
        args.workers = os.cpu_count() or 1

    # Create global config from CLI arguments
    config = Config(
        sources=args.sources,
        destination=args.destination,
        verbose=args.verbose or args.debug,
        skip_extensions=args.skip_extensions,
        dry_run=args.dry_run,
        workers=args.workers,
        debug=args.debug,
        copy_strategy=args.copy_strategy,
    )

    try:
        logger.info(f"Using {config.workers} worker(s) for processing")
        logger.info(f"Using copy strategy: {config.copy_strategy}")
        file_count = hardlink_copy_recursive(config)
        strategy_name = (
            "hardlinked"
            if config.copy_strategy == "hardlink"
            else "copied"
            if config.copy_strategy == "copy"
            else "processed (hardlink or copy)"
        )
        logger.info(f"Successfully {strategy_name} {file_count} files")
    except ValueError as e:
        if config.debug:
            logger.exception(f"Error: {e}")
        else:
            logger.error(f"Error: {e}")
        return 1
    except Exception as e:
        if config.debug:
            logger.exception(f"Unexpected error: {e}")
        else:
            logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    main()
