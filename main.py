import os
import sys
import argparse
import logging
from pathlib import Path
from multiprocessing import Pool
from dataclasses import dataclass
from functools import partial

# Configure logger
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    """Global configuration for the hardlink copy operation."""

    sources: list[Path]
    destination: Path
    verbose: bool = False
    skip_extensions: list[str] | None = None
    dry_run: bool = False
    workers: int | None = None

    def __post_init__(self):
        """Normalize paths and skip extensions."""
        # Normalize sources list
        normalized_sources = [Path(src).resolve() for src in self.sources]
        object.__setattr__(self, "sources", normalized_sources)
        object.__setattr__(self, "destination", Path(self.destination).resolve())
        if self.skip_extensions is None:
            object.__setattr__(self, "skip_extensions", [])
        # Ensure extensions start with a dot
        skip_exts = [
            ext if ext.startswith(".") else f".{ext}" for ext in self.skip_extensions
        ]
        object.__setattr__(self, "skip_extensions", skip_exts)


# Global config instance
config: Config | None = None
# Global debug flag
debug: bool = False


@dataclass
class FileToProcess:
    """Dataclass representing a file to be hardlinked."""

    src_path: Path
    dst_path: Path
    rel_path: Path


def _process_file(file_info: FileToProcess, dry_run: bool, verbose: bool) -> int:
    """Helper function to process a single file for parallel execution."""
    try:
        if not dry_run:
            os.link(file_info.src_path, file_info.dst_path)
        if verbose:
            logger.info(f"Hardlinked: {file_info.rel_path}")
        return 1
    except OSError as e:
        if debug:
            logger.exception(f"Error hardlinking {file_info.rel_path}")
        else:
            logger.error(f"Error hardlinking {file_info.rel_path}: {e}")
        return 0


def hardlink_copy_recursive(cfg: Config) -> int:
    """Hardlink copy all files from src directories to dst, preserving directory structure.

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

    # Collect all files to process from all sources
    files_to_process = []
    parent_dirs = set()

    for src_dir in cfg.sources:
        for src_path in src_dir.rglob("*"):
            # Skip directories
            if src_path.is_dir():
                continue

            # Skip files with extensions in skip list
            if src_path.suffix in cfg.skip_extensions:
                continue

            # Calculate relative path from source root
            rel_path = src_path.relative_to(src_dir)
            dst_path = cfg.destination / rel_path

            # Track parent directories that need to be created
            parent_dirs.add(dst_path.parent)

            # Skip if destination file already exists
            if dst_path.exists() or dst_path.is_symlink():
                if cfg.verbose:
                    logger.info(f"Skipped (already exists): {rel_path}")
                continue

            files_to_process.append(
                FileToProcess(
                    src_path=src_path,
                    dst_path=dst_path,
                    rel_path=rel_path,
                )
            )

    # Create all parent directories sequentially
    if not cfg.dry_run:
        for parent_dir in sorted(parent_dirs):
            parent_dir.mkdir(parents=True, exist_ok=True)

    # Process files in parallel
    file_count = 0
    if files_to_process:
        process_worker = partial(
            _process_file, dry_run=cfg.dry_run, verbose=cfg.verbose
        )
        with Pool(processes=cfg.workers) as pool:
            results = pool.map(process_worker, files_to_process)
            file_count = sum(results)

    return file_count


def main():
    global config, debug

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

    args = parser.parse_args()

    # Set debug flag
    debug = args.debug

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

    # Create global config from CLI arguments
    config = Config(
        sources=args.sources,
        destination=args.destination,
        verbose=args.verbose or args.debug,
        skip_extensions=args.skip_extensions,
        dry_run=args.dry_run,
        workers=args.workers,
    )

    try:
        file_count = hardlink_copy_recursive(config)
        logger.info(f"Successfully hardlinked {file_count} files")
    except ValueError as e:
        if debug:
            logger.exception(f"Error: {e}")
        else:
            logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        if debug:
            logger.exception(f"Unexpected error: {e}")
        else:
            logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
