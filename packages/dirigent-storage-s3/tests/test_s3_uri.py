"""The hermetic lane: URI parsing, glob translation, config defaults, and client plumbing."""

from typing import Any

import pytest
from pluginkit import PluginManager
from pydantic import SecretStr

from dirigent_common import API_VERSION
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers
from dirigent_storage_s3 import (
    MULTIPART_THRESHOLD,
    PART_SIZE,
    PATH_ADDRESSING,
    VIRTUAL_ADDRESSING,
    InvalidS3Uri,
    S3ConnectionKind,
    S3StorageBackend,
    S3StorageConfig,
    S3StoragePlugin,
    client_kwargs,
    fixed_prefix,
    is_pattern,
    matches_pattern,
    object_uri,
    parse_s3_uri,
    plugin,
)


@pytest.mark.parametrize(
    ("uri", "bucket", "key"),
    [
        ("s3://bucket/key", "bucket", "key"),
        ("s3://bucket/nested/path/to/object.csv", "bucket", "nested/path/to/object.csv"),
        ("s3://bucket/", "bucket", ""),
        ("s3://bucket", "bucket", ""),
        ("s3://bucket//double", "bucket", "double"),
        ("s3://bucket/trailing/", "bucket", "trailing/"),
        ("s3://my-bucket.with.dots/a b c.txt", "my-bucket.with.dots", "a b c.txt"),
        ("s3://bucket/glob/*.csv", "bucket", "glob/*.csv"),
        # urlsplit lower-cases the scheme, as RFC 3986 says it may; the facade dispatches the same way.
        ("S3://bucket/key", "bucket", "key"),
    ],
)
def test_parse_splits_a_uri_into_bucket_and_key(uri: str, bucket: str, key: str) -> None:
    assert parse_s3_uri(uri) == (bucket, key)


@pytest.mark.parametrize(
    ("uri", "reason"),
    [
        ("bucket/key", "names no scheme"),
        ("/absolute/path", "names no scheme"),
        ("file:///tmp/key", "expected scheme"),
        ("s3a://bucket/key", "expected scheme"),
        ("https://bucket.s3.amazonaws.com/key", "expected scheme"),
        ("s3:///key", "names no bucket"),
        ("s3://", "names no bucket"),
        ("s3://bucket:9000/key", "not a bare bucket name"),
        ("s3://user@bucket/key", "not a bare bucket name"),
        ("s3://bucket/key?versionId=2", "may be a URI delimiter"),
        ("s3://bucket/key#fragment", "may be a URI delimiter"),
    ],
)
def test_parse_refuses_anything_that_is_not_an_addressable_object(uri: str, reason: str) -> None:
    with pytest.raises(InvalidS3Uri) as caught:
        parse_s3_uri(uri)
    assert reason in str(caught.value)
    assert caught.value.uri == uri


def test_object_uri_round_trips_through_parse() -> None:
    assert parse_s3_uri(object_uri("bucket", "a/b/c.txt")) == ("bucket", "a/b/c.txt")


def test_locate_refuses_a_uri_that_names_only_a_bucket() -> None:
    backend = S3StorageBackend()
    with pytest.raises(InvalidS3Uri, match="no key"):
        backend.locate("s3://bucket/")


def test_locate_allows_an_empty_key_when_listing_a_whole_bucket() -> None:
    backend = S3StorageBackend()
    assert backend.locate("s3://bucket", require_key=False) == ("bucket", "")


def test_uri_for_renders_what_locate_accepts() -> None:
    backend = S3StorageBackend()
    assert backend.uri_for("bucket", "a/b") == "s3://bucket/a/b"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("data/", False),
        ("", False),
        ("data/*.csv", True),
        ("data/2026-0?/rows", True),
        ("data/[ab]/rows", True),
    ],
)
def test_is_pattern_spots_the_glob_characters(location: str, expected: bool) -> None:
    assert is_pattern(location) is expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("data/rows.csv", "data/rows.csv"),
        ("data/", "data/"),
        ("", ""),
        ("data/*.csv", "data/"),
        ("data/2026/*/*.csv", "data/2026/"),
        ("*.csv", ""),
        ("data/ro?s.csv", "data/ro"),
        ("data/[ab]/x", "data/"),
        ("data/part*[0-9]?", "data/part"),
    ],
)
def test_fixed_prefix_stops_at_the_first_glob_character(pattern: str, expected: str) -> None:
    assert fixed_prefix(pattern) == expected


@pytest.mark.parametrize(
    ("key", "pattern", "expected"),
    [
        ("data/rows.csv", "data/", True),
        ("data/2026/rows.csv", "data/", True),
        ("other/rows.csv", "data/", False),
        ("anything", "", True),
        ("data/rows.csv", "data/*.csv", True),
        ("data/rows.json", "data/*.csv", False),
        ("data/2026/01/rows.csv", "data/*.csv", True),
        ("data/rows.CSV", "data/*.csv", False),
        ("data/row5.csv", "data/row?.csv", True),
        ("data/rows.csv", "data/row?.csv", True),
        ("data/a/x", "data/[ab]/x", True),
        ("data/c/x", "data/[ab]/x", False),
    ],
)
def test_matches_pattern_is_prefix_for_plain_and_fnmatch_for_globs(key: str, pattern: str, expected: bool) -> None:
    assert matches_pattern(key, pattern) is expected


def test_a_star_crosses_a_slash_unlike_the_file_backend() -> None:
    assert matches_pattern("data/2026/01/rows.csv", "data/*.csv")
    assert matches_pattern("data/2026/01/rows.csv", "data/*")


def test_the_fixed_prefix_never_excludes_a_key_the_pattern_matches() -> None:
    pattern = "data/2026/*/rows-*.csv"
    prefix = fixed_prefix(pattern)
    for key in ("data/2026/01/rows-a.csv", "data/2026/12/deep/rows-b.csv"):
        assert matches_pattern(key, pattern)
        assert key.startswith(prefix)


def test_config_defaults_are_aws_with_virtual_addressing() -> None:
    config = S3StorageConfig()
    assert config.endpoint_url is None
    assert config.region == "us-east-1"
    assert config.access_key_id is None
    assert config.secret_access_key is None
    assert config.path_style is False
    assert config.verify_tls is True
    assert config.bucket is None


def test_the_secret_is_redacted_when_the_config_is_rendered() -> None:
    config = S3StorageConfig(secret_access_key=SecretStr("hunter2"))
    assert "hunter2" not in repr(config)
    assert config.secret_access_key is not None
    assert config.secret_access_key.get_secret_value() == "hunter2"


def test_default_client_kwargs_carry_no_endpoint_and_no_credentials() -> None:
    kwargs = client_kwargs(S3StorageConfig())
    assert kwargs["service_name"] == "s3"
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["verify"] is True
    assert kwargs["config"].s3 == {"addressing_style": VIRTUAL_ADDRESSING}
    assert "endpoint_url" not in kwargs
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs


def test_self_hosted_client_kwargs_carry_the_endpoint_and_path_addressing() -> None:
    config = S3StorageConfig(
        endpoint_url="http://127.0.0.1:9000",
        region="eu-north-1",
        access_key_id="an-access-key",
        secret_access_key=SecretStr("a-secret-key"),
        path_style=True,
        verify_tls=False,
    )
    kwargs = client_kwargs(config)
    assert kwargs["endpoint_url"] == "http://127.0.0.1:9000"
    assert kwargs["region_name"] == "eu-north-1"
    assert kwargs["aws_access_key_id"] == "an-access-key"
    assert kwargs["aws_secret_access_key"] == "a-secret-key"
    assert kwargs["verify"] is False
    assert kwargs["config"].s3 == {"addressing_style": PATH_ADDRESSING}


def test_the_part_size_is_the_s3_minimum_so_nothing_smaller_pays_for_multipart() -> None:
    assert PART_SIZE == 5 * 1024 * 1024
    assert MULTIPART_THRESHOLD == PART_SIZE


def test_the_backend_registers_the_s3_scheme_and_its_config_model() -> None:
    backend = S3StorageBackend()
    assert backend.scheme == "s3"
    assert backend.config_model is S3StorageConfig
    assert backend.config == S3StorageConfig()


def test_the_plugin_contributes_the_backend_and_the_connection_kind() -> None:
    contribution = S3StoragePlugin().contribute()
    assert contribution.api_version == API_VERSION
    assert [backend.scheme for backend in contribution.storage_backends] == ["s3"]
    assert [connection.id for connection in contribution.connection_kinds] == ["s3"]
    assert contribution.block_ids() == []


def test_the_connection_kind_shares_the_backend_config_model() -> None:
    assert S3ConnectionKind.id == "s3"
    assert S3ConnectionKind.config_model is S3StorageConfig


def test_the_plugin_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert manager.get_plugin("storage-s3") is not None
    schemes = [
        backend.scheme for contribution in manager.caller(contribute)() for backend in contribution.storage_backends
    ]
    assert "s3" in schemes


async def test_a_check_against_an_unusable_endpoint_reports_rather_than_raises() -> None:
    config = S3StorageConfig(
        endpoint_url="not a url",
        access_key_id="key",
        secret_access_key=SecretStr("secret"),
        path_style=True,
    )
    report = await S3ConnectionKind().check(config)
    assert report.healthy is False
    assert report.detail


def test_plugin_is_the_singleton_the_entry_point_names() -> None:
    exported: Any = plugin
    assert isinstance(exported, S3StoragePlugin)
