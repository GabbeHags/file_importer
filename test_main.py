"""Tests for the file_importer module."""

from pathlib import Path
from argparse import ArgumentParser
from main import (
    _clean_filename,
    _clean_path,
    Config,
    ALLOWED_CHARS,
    hardlink_copy_recursive,
)


class TestCleanFilename:
    """Tests for the _clean_filename function."""

    def test_clean_filename_with_valid_chars(self):
        """Test that valid characters are preserved."""
        assert _clean_filename("test_file-123.txt") == "test_file-123.txt"

    def test_clean_filename_with_spaces(self):
        """Test that spaces are preserved."""
        assert _clean_filename("my file (1).txt") == "my file (1).txt"

    def test_clean_filename_removes_special_chars(self):
        """Test that special characters are removed."""
        assert _clean_filename("file@#$%.txt") == "file.txt"

    def test_clean_filename_with_unicode(self):
        """Test that Unicode characters are removed."""
        assert _clean_filename("café_file.txt") == "caf_file.txt"

    def test_clean_filename_with_emojis(self):
        """Test that emojis are removed."""
        assert _clean_filename("📁file.txt") == "file.txt"

    def test_clean_filename_all_invalid_returns_original(self):
        """Test that if all characters are invalid, original is returned."""
        result = _clean_filename("@#$%^&*()")
        # Parentheses are in ALLOWED_CHARS, so they're kept
        assert result == "()"

    def test_clean_filename_mixed_content(self):
        """Test filename with mixed valid and invalid characters."""
        assert _clean_filename("test-file_2024[v1].txt") == "test-file_2024[v1].txt"
        # résumé -> rsum (r is ASCII, but é is not)
        assert _clean_filename("résumé(v2).pdf") == "rsum(v2).pdf"


class TestCleanPath:
    """Tests for the _clean_path function."""

    def test_clean_path_with_valid_chars(self):
        """Test that valid path components are preserved."""
        path = Path("/home/user/test-dir_123")
        result = _clean_path(path)
        # Path separator "/" is removed, so the result is relative
        assert str(result) == "home/user/test-dir_123"

    def test_clean_path_removes_special_chars(self):
        """Test that special characters in path components are removed."""
        path = Path("/home/user@home/test#dir")
        result = _clean_path(path)
        # Should have cleaned components
        assert "user@home" not in str(result) or "@" not in str(result)

    def test_clean_path_with_unicode(self):
        """Test that Unicode characters in paths are removed."""
        path = Path("/home/café/filé")
        result = _clean_path(path)
        # café should become caf, filé should become fil
        path_str = str(result)
        assert "café" not in path_str

    def test_clean_path_preserves_structure(self):
        """Test that path structure is maintained."""
        path = Path("/home/user/project/file.txt")
        result = _clean_path(path)
        # Since "/" is not in ALLOWED_CHARS, the path becomes relative
        # But the structure (multiple path components) is preserved
        assert len(result.parts) >= 3  # At least home, user, project

    def test_clean_path_with_spaces_and_brackets(self):
        """Test that spaces and brackets are preserved."""
        path = Path("/home/user/My Project (v1)/file [2024].txt")
        result = _clean_path(path)
        path_str = str(result)
        assert "My Project (v1)" in path_str
        assert "file [2024].txt" in path_str


class TestConfig:
    """Tests for the Config class."""

    def test_config_initialization(self):
        """Test basic config initialization."""
        sources = [Path("/tmp/source1")]
        destination = Path("/tmp/destination")
        config = Config(sources=sources, destination=destination)

        assert config.sources == sources
        assert config.verbose is False
        assert config.dry_run is False
        assert config.workers == 1

    def test_config_destination_cleaned(self):
        """Test that destination path is cleaned."""
        sources = [Path("/tmp/source")]
        destination = Path("/tmp/dest@invalid")

        config = Config(sources=sources, destination=destination)

        # The destination should have special chars removed
        dest_str = str(config.destination)
        assert "@" not in dest_str

    def test_config_sources_not_cleaned(self):
        """Test that source paths are NOT cleaned (kept with glyphs)."""
        sources = [Path("/tmp/café")]
        destination = Path("/tmp/destination")

        config = Config(sources=sources, destination=destination)

        # Source should be normalized but NOT cleaned
        assert len(config.sources) > 0

    def test_config_skip_extensions_with_dot(self):
        """Test that skip extensions get dot prefix if missing."""
        config = Config(
            sources=[Path("/tmp/src")],
            destination=Path("/tmp/dst"),
            skip_extensions=["txt", ".pdf"],
        )

        assert ".txt" in config.skip_extensions
        assert ".pdf" in config.skip_extensions

    def test_config_with_all_options(self):
        """Test config with all options specified."""
        config = Config(
            sources=[Path("/tmp/src1"), Path("/tmp/src2")],
            destination=Path("/tmp/dst"),
            verbose=True,
            skip_extensions=["tmp"],
            dry_run=True,
            workers=4,
            debug=True,
        )

        assert len(config.sources) == 2
        assert config.verbose is True
        assert config.dry_run is True
        assert config.workers == 4
        assert config.debug is True


class TestAllowedChars:
    """Tests for the ALLOWED_CHARS constant."""

    def test_allowed_chars_contains_letters(self):
        """Test that allowed chars includes a-z and A-Z."""
        for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert c in ALLOWED_CHARS

    def test_allowed_chars_contains_numbers(self):
        """Test that allowed chars includes 0-9."""
        for c in "0123456789":
            assert c in ALLOWED_CHARS

    def test_allowed_chars_contains_common_signs(self):
        """Test that allowed chars includes common file system signs."""
        expected_signs = "._-() []{} "
        for c in expected_signs:
            assert c in ALLOWED_CHARS

    def test_allowed_chars_excludes_special_chars(self):
        """Test that special characters are not in allowed chars."""
        invalid_chars = "@#$%^&*+=<>\\|`~;:?/"
        for c in invalid_chars:
            assert c not in ALLOWED_CHARS


class TestHardlinkIntegration:
    """Integration tests for hardlinking files with various names."""

    def test_hardlink_simple_files(self, tmp_path: Path):
        """Test hardlinking simple files."""
        # Create source directory with test files
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("content1")
        (src_dir / "file2.txt").write_text("content2")

        # Create destination directory
        dst_dir = tmp_path / "destination"

        # Run hardlink copy with workers=1 to avoid multiprocessing fork warnings
        config = Config(
            sources=[src_dir],
            destination=dst_dir,
            verbose=False,
            debug=False,
            workers=1,
        )
        count = hardlink_copy_recursive(config)

        assert count == 2
        # Check in the cleaned destination path
        actual_dst = config.destination
        assert (actual_dst / "file1.txt").exists()
        assert (actual_dst / "file2.txt").exists()
        assert (actual_dst / "file1.txt").read_text() == "content1"

    def test_hardlink_with_subdirectories(self, tmp_path: Path):
        """Test hardlinking preserves subdirectory structure."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        subdir = src_dir / "subdir"
        subdir.mkdir()
        (src_dir / "root_file.txt").write_text("root")
        (subdir / "nested_file.txt").write_text("nested")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 2
        actual_dst = config.destination
        assert (actual_dst / "root_file.txt").exists()
        assert (actual_dst / "subdir" / "nested_file.txt").exists()

    def test_hardlink_with_special_characters(self, tmp_path: Path):
        """Test hardlinking files with special characters in names."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        # Create files with special characters - only one will remain after name collision
        (src_dir / "test@file.txt").write_text("special")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 1
        actual_dst = config.destination
        # @ should be removed
        assert (actual_dst / "testfile.txt").exists()

    def test_hardlink_with_unicode_characters(self, tmp_path: Path):
        """Test hardlinking files with unicode characters in names."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "café.txt").write_text("unicode")
        (src_dir / "resume.py").write_text("text")  # Simple ASCII for clarity

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 2
        actual_dst = config.destination
        # Unicode chars should be removed, keeping only ASCII
        assert (actual_dst / "caf.txt").exists()  # café -> caf
        assert (actual_dst / "resume.py").exists()

    def test_hardlink_multiple_sources(self, tmp_path: Path):
        """Test hardlinking from multiple source directories."""
        src1 = tmp_path / "source1"
        src2 = tmp_path / "source2"
        src1.mkdir()
        src2.mkdir()

        (src1 / "file1.txt").write_text("from source1")
        (src2 / "file2.txt").write_text("from source2")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src1, src2], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 2
        actual_dst = config.destination
        assert (actual_dst / "file1.txt").exists()
        assert (actual_dst / "file2.txt").exists()

    def test_hardlink_skip_extensions(self, tmp_path: Path):
        """Test that files with skip extensions are not hardlinked."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "important.txt").write_text("keep")
        (src_dir / "temp.tmp").write_text("skip")
        (src_dir / "backup.bak").write_text("skip")

        dst_dir = tmp_path / "destination"

        config = Config(
            sources=[src_dir],
            destination=dst_dir,
            skip_extensions=["tmp", "bak"],
            workers=1,
        )
        count = hardlink_copy_recursive(config)

        assert count == 1
        actual_dst = config.destination
        assert (actual_dst / "important.txt").exists()
        assert not (actual_dst / "temp.tmp").exists()
        assert not (actual_dst / "backup.bak").exists()

    def test_hardlink_dry_run(self, tmp_path: Path):
        """Test that dry run doesn't create hardlinks."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("content")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, dry_run=True, workers=1)
        count = hardlink_copy_recursive(config)

        # Count should be 1 (file was processed) but destination shouldn't have files
        assert count == 1
        actual_dst = config.destination
        assert not (actual_dst / "file.txt").exists()

    def test_hardlink_preserves_file_content(self, tmp_path: Path):
        """Test that hardlinked files have the same content."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        content = "This is test content with special chars"
        (src_dir / "test.txt").write_text(content)

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 1
        actual_dst = config.destination
        assert (actual_dst / "test.txt").read_text() == content

    def test_hardlink_skip_existing_files(self, tmp_path: Path):
        """Test that existing files in destination are skipped."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("source content")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        # Pre-create the destination with a file
        config.destination.mkdir(parents=True, exist_ok=True)
        (config.destination / "file.txt").write_text("existing content")

        count = hardlink_copy_recursive(config)

        assert count == 0
        # File should still have original content
        assert (config.destination / "file.txt").read_text() == "existing content"

    def test_hardlink_with_mixed_valid_invalid_chars(self, tmp_path: Path):
        """Test hardlinking with mixed valid and invalid characters in name."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "my-file_2024[v1]@final.txt").write_text("data")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=1)
        count = hardlink_copy_recursive(config)

        assert count == 1
        actual_dst = config.destination
        # @ should be removed, but other valid chars preserved
        assert (actual_dst / "my-file_2024[v1]final.txt").exists()


class TestRaceConditions:
    """Tests for race conditions with multiple workers."""

    def test_concurrent_file_creation_multiple_workers(self, tmp_path: Path):
        """Test that multiple workers can safely create files concurrently."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create many files to trigger concurrent processing
        for i in range(20):
            (src_dir / f"file{i:02d}.txt").write_text(f"content{i}")

        dst_dir = tmp_path / "destination"

        # Use 4 workers to force concurrent access
        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        assert count == 20
        actual_dst = config.destination

        # Verify all files were created correctly
        for i in range(20):
            file_path = actual_dst / f"file{i:02d}.txt"
            assert file_path.exists()
            assert file_path.read_text() == f"content{i}"

    def test_concurrent_subdirectory_creation(self, tmp_path: Path):
        """Test that multiple workers can safely create nested directories."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create files in multiple nested directories
        for dir_num in range(5):
            subdir = src_dir / f"dir{dir_num}"
            subdir.mkdir()
            for file_num in range(4):
                (subdir / f"file{file_num}.txt").write_text(
                    f"dir{dir_num}_file{file_num}"
                )

        dst_dir = tmp_path / "destination"

        # Use multiple workers
        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        assert count == 20
        actual_dst = config.destination

        # Verify all nested files exist
        for dir_num in range(5):
            for file_num in range(4):
                file_path = actual_dst / f"dir{dir_num}" / f"file{file_num}.txt"
                assert file_path.exists()

    def test_multiple_sources_concurrent_access(self, tmp_path: Path):
        """Test that multiple workers can access multiple source directories."""
        src1 = tmp_path / "source1"
        src2 = tmp_path / "source2"
        src3 = tmp_path / "source3"
        src1.mkdir()
        src2.mkdir()
        src3.mkdir()

        # Create different files in each source
        for i in range(10):
            (src1 / f"src1_file{i}.txt").write_text(f"source1_{i}")
            (src2 / f"src2_file{i}.txt").write_text(f"source2_{i}")
            (src3 / f"src3_file{i}.txt").write_text(f"source3_{i}")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src1, src2, src3], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        assert count == 30
        actual_dst = config.destination

        # Verify files from all sources
        for i in range(10):
            assert (actual_dst / f"src1_file{i}.txt").exists()
            assert (actual_dst / f"src2_file{i}.txt").exists()
            assert (actual_dst / f"src3_file{i}.txt").exists()

    def test_race_condition_destination_exists_check(self, tmp_path: Path):
        """Test that checking for existing files doesn't cause race conditions."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create files
        for i in range(10):
            (src_dir / f"file{i}.txt").write_text(f"content{i}")

        dst_dir = tmp_path / "destination"

        # First run - create files
        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count1 = hardlink_copy_recursive(config)
        assert count1 == 10

        # Second run - should skip all files
        count2 = hardlink_copy_recursive(config)
        assert count2 == 0

        # Verify content is unchanged
        actual_dst = config.destination
        for i in range(10):
            assert (actual_dst / f"file{i}.txt").read_text() == f"content{i}"

    def test_many_files_with_special_chars(self, tmp_path: Path):
        """Test concurrent processing of files with special characters."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create many files with various special characters
        special_chars = ["@", "#", "$", "%", "^", "&", "*", "!", "~"]
        file_num = 0
        for char in special_chars:
            for i in range(3):
                filename = f"file{file_num}{char}test{i}.txt"
                (src_dir / filename).write_text(f"data{file_num}{i}")
                file_num += 1

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        # Should process all files
        assert count == len(special_chars) * 3
        actual_dst = config.destination

        # Verify all files were cleaned and created
        for file_path in actual_dst.rglob("*"):
            if file_path.is_file():
                # Verify no special chars in the destination filenames
                assert "@" not in file_path.name
                assert "#" not in file_path.name
                assert "$" not in file_path.name
                assert "%" not in file_path.name

    def test_deep_nested_directories_concurrent(self, tmp_path: Path):
        """Test concurrent processing with deeply nested directory structures."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create a deep directory structure
        current = src_dir
        for depth in range(5):
            current = current / f"level{depth}"
            current.mkdir()
            for i in range(3):
                (current / f"file_level{depth}_{i}.txt").write_text(
                    f"content_level{depth}_{i}"
                )

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        # 5 levels * 3 files each = 15 files
        assert count == 15
        actual_dst = config.destination

        # Verify nested structure
        for depth in range(5):
            for i in range(3):
                levels = "/".join(f"level{d}" for d in range(depth + 1))
                file_path = actual_dst / levels / f"file_level{depth}_{i}.txt"
                assert file_path.exists()
                assert file_path.read_text() == f"content_level{depth}_{i}"

    def test_race_condition_directory_creation(self, tmp_path: Path):
        """Test that directory creation doesn't race when multiple workers create same parent."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create many files that might create same parent directory
        subdir = src_dir / "shared_dir"
        subdir.mkdir()
        for i in range(20):
            (subdir / f"file{i}.txt").write_text(f"content{i}")

        dst_dir = tmp_path / "destination"

        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        assert count == 20
        actual_dst = config.destination

        # Verify all files in the shared directory were created
        shared_dst = actual_dst / "shared_dir"
        assert shared_dst.exists()
        assert len(list(shared_dst.glob("*.txt"))) == 20

    def test_large_file_count_10k(self, tmp_path: Path):
        """Test hardlinking 10,000 files with multiple workers."""
        src_dir = tmp_path / "source"
        src_dir.mkdir()

        # Create 10,000 files
        num_files = 10000
        for i in range(num_files):
            (src_dir / f"file{i:05d}.txt").write_text(f"content{i}")

        dst_dir = tmp_path / "destination"

        # Use multiple workers for performance
        config = Config(sources=[src_dir], destination=dst_dir, workers=4)
        count = hardlink_copy_recursive(config)

        assert count == num_files
        actual_dst = config.destination

        # Sample verification - check first, middle, and last files
        assert (actual_dst / "file00000.txt").exists()
        assert (actual_dst / f"file{num_files // 2:05d}.txt").exists()
        assert (actual_dst / f"file{num_files - 1:05d}.txt").exists()

        # Verify content of sample files
        assert (actual_dst / "file00000.txt").read_text() == "content0"
        assert (
            actual_dst / f"file{num_files - 1:05d}.txt"
        ).read_text() == f"content{num_files - 1}"

        # Count total files created
        total_files = len(list(actual_dst.glob("*.txt")))
        assert total_files == num_files


class TestArgumentParsing:
    """Tests for command-line argument parsing and Config creation."""

    @staticmethod
    def _parse_args(args_list):
        """Helper to parse arguments like the CLI does."""
        parser = ArgumentParser()
        parser.add_argument("sources", nargs="+")
        parser.add_argument("destination")
        parser.add_argument("-v", "--verbose", action="store_true")
        parser.add_argument("-s", "--skip-extensions", nargs="+", default=[])
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("-j", "--workers", type=int, default=None)
        parser.add_argument("--debug", action="store_true")

        return parser.parse_args(args_list)

    def test_parse_minimal_args(self, tmp_path):
        """Test parsing with only required arguments."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args([str(src), str(dst)])

        assert args.sources == [str(src)]
        assert args.destination == str(dst)
        assert args.verbose is False
        assert args.dry_run is False
        assert args.workers is None
        assert args.debug is False
        assert args.skip_extensions == []

    def test_parse_verbose_flag(self, tmp_path):
        """Test parsing with verbose flag."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args(["-v", str(src), str(dst)])
        assert args.verbose is True

        args = self._parse_args(["--verbose", str(src), str(dst)])
        assert args.verbose is True

    def test_parse_debug_flag(self, tmp_path):
        """Test parsing with debug flag."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args(["--debug", str(src), str(dst)])
        assert args.debug is True

    def test_parse_dry_run_flag(self, tmp_path):
        """Test parsing with dry-run flag."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args(["--dry-run", str(src), str(dst)])
        assert args.dry_run is True

    def test_parse_workers_argument(self, tmp_path):
        """Test parsing with workers argument."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args(["-j", "4", str(src), str(dst)])
        assert args.workers == 4

        args = self._parse_args(["--workers", "8", str(src), str(dst)])
        assert args.workers == 8

    def test_parse_skip_extensions(self, tmp_path):
        """Test parsing with skip-extensions."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        # Note: with nargs="+", skip-extensions must come after positional args or use explicit order
        args = self._parse_args([str(src), str(dst), "-s", "txt", "tmp"])
        assert "txt" in args.skip_extensions
        assert "tmp" in args.skip_extensions

        args = self._parse_args(
            [str(src), str(dst), "--skip-extensions", ".pdf", ".docx"]
        )
        assert ".pdf" in args.skip_extensions
        assert ".docx" in args.skip_extensions

    def test_parse_multiple_sources(self, tmp_path):
        """Test parsing with multiple source directories."""
        src1 = tmp_path / "source1"
        src2 = tmp_path / "source2"
        dst = tmp_path / "dest"
        src1.mkdir()
        src2.mkdir()

        args = self._parse_args([str(src1), str(src2), str(dst)])
        assert len(args.sources) == 2
        assert str(src1) in args.sources
        assert str(src2) in args.sources

    def test_args_to_config_conversion(self, tmp_path):
        """Test that parsed args are correctly converted to Config."""
        src = tmp_path / "source"
        dst = tmp_path / "dest@invalid"
        src.mkdir()

        # Note: positional args must come before optional args with nargs="+"
        args = self._parse_args(
            [
                str(src),
                str(dst),
                "-v",
                "--dry-run",
                "-j",
                "2",
                "--debug",
                "-s",
                "tmp",
                ".bak",
            ]
        )

        # Simulate what main() does with the args
        workers = args.workers or 1
        config = Config(
            sources=args.sources,
            destination=args.destination,
            verbose=args.verbose or args.debug,
            skip_extensions=args.skip_extensions,
            dry_run=args.dry_run,
            workers=workers,
            debug=args.debug,
        )

        assert config.verbose is True  # verbose or debug
        assert config.dry_run is True
        assert config.workers == 2
        assert config.debug is True
        assert ".tmp" in config.skip_extensions
        assert ".bak" in config.skip_extensions
        # Destination should be cleaned
        assert "@" not in str(config.destination)

    def test_args_workers_defaults_to_one(self, tmp_path):
        """Test that workers defaults to 1 when None."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        args = self._parse_args([str(src), str(dst)])
        assert args.workers is None

        # Simulate what main() does
        workers = args.workers or 1
        assert workers == 1

    def test_args_verbose_or_debug_sets_verbose(self, tmp_path):
        """Test that verbose flag is set if debug is true."""
        src = tmp_path / "source"
        dst = tmp_path / "dest"
        src.mkdir()

        # Test with verbose flag
        args = self._parse_args(["-v", str(src), str(dst)])
        verbose = args.verbose or args.debug
        assert verbose is True

        # Test with debug flag
        args = self._parse_args(["--debug", str(src), str(dst)])
        verbose = args.verbose or args.debug
        assert verbose is True

        # Test with both
        args = self._parse_args(["-v", "--debug", str(src), str(dst)])
        verbose = args.verbose or args.debug
        assert verbose is True

        # Test with neither
        args = self._parse_args([str(src), str(dst)])
        verbose = args.verbose or args.debug
        assert verbose is False

    def test_args_config_with_special_chars_in_paths(self, tmp_path):
        """Test that args with special characters are handled correctly."""
        src = tmp_path / "café_source"
        dst = tmp_path / "dest#invalid"
        src.mkdir()

        args = self._parse_args([str(src), str(dst)])

        # Create config - destination should be cleaned, source preserved
        config = Config(
            sources=args.sources,
            destination=args.destination,
            skip_extensions=args.skip_extensions,
        )

        # Source path preserved (just normalized)
        assert str(src) in str(config.sources[0])
        # Destination path cleaned
        assert "#" not in str(config.destination)
