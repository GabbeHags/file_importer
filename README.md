# File Importer - Hardlink Copy Utility

A high-performance utility for recursively hardlinking files from one or more source directories to a destination while preserving the complete directory structure.

## Features

- **Multiple Source Directories**: Copy from one or more source directories in a single operation
- **Recursive Hardlinking**: Efficiently copy files using hardlinks instead of full file copies
- **Directory Structure Preservation**: All subdirectories and relative paths are maintained in the destination
- **Extension Filtering**: Skip files with specific extensions (e.g., `.!qB`, `.tmp`)
- **Parallel Processing**: Process multiple files concurrently using multiprocessing for improved performance
- **Dry Run Mode**: Preview what would be copied without actually performing the operation
- **Existing File Handling**: Skip files that already exist in the destination directory
- **Verbose Logging**: Detailed logging with timestamps for monitoring the operation

## Installation

```bash
cd file_importer
uv sync
```

### Requirements

- Python 3.12+
- `uv` package manager

## Usage

### Basic Usage

Copy all files from one or more source directories to destination:

```bash
# Single source directory
uv run main.py /path/to/source /path/to/destination

# Multiple source directories
uv run main.py /path/to/source1 /path/to/source2 /path/to/source3 /path/to/destination
```

### Options

- `-v, --verbose`: Enable verbose logging with DEBUG level details
- `-s, --skip-extensions`: Skip files with specific extensions
  ```bash
  uv run main.py /src /dst -s .qB .tmp .bak
  ```
- `--dry-run`: Simulate the operation without creating hardlinks
  ```bash
  uv run main.py /src /dst --dry-run
  ```
- `-j, --workers`: Number of parallel workers (default: CPU count)
  ```bash
  uv run main.py /src /dst -j 4
  ```
- `--debug`: Show full traceback on errors and detailed debugging information
  ```bash
  uv run main.py /src /dst --debug
  ```
- `--copy-strategy`: File copying strategy (default: hardlink)
  - `hardlink`: Use hardlinks only, fails if cross-device link not supported
  - `auto`: Try hardlink first, fall back to copy on cross-device errors (default)
  - `copy`: Use regular file copy only
  ```bash
  uv run main.py /src /dst --copy-strategy hardlink
  ```

### Examples

```bash
# Single source directory
uv run main.py ~/my_project ~/backup

# Multiple source directories
uv run main.py ~/project1 ~/project2 ~/project3 ~/backup

# Verbose with extension filtering
uv run main.py ~/my_project ~/backup -v -s .qB .tmp

# Preview operation with 8 workers
uv run main.py ~/my_project ~/backup --dry-run -j 8

# Dry run with verbose output
uv run main.py ~/my_project ~/backup --dry-run -v

# Debug mode with full traceback
uv run main.py ~/my_project ~/backup --debug

# Force regular copy instead of hardlink
uv run main.py ~/my_project ~/backup --copy-strategy copy

# Use copy fallback for cross-device scenarios
uv run main.py ~/my_project ~/backup --copy-strategy auto
```
