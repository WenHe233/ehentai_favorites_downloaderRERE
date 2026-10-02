from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.output_template import (
    OutputTemplateError, OutputTemplateSettings, resolve_output_targets,
    _truncate_filename_if_needed, _filesystem_length, with_temp_suffix,
)


@pytest.mark.parametrize("title", ["x" * 400, "Title." + "中" * 300, "😀" * 200, "日本語." * 90, "CON", "NUL.txt", "COM1", "trailing. ", 'a/b:c*?"<>|'])
def test_legal_long_names(tmp_path, title):
    config = OutputTemplateSettings("./downloads/{title}.zip", "rename", True, 80, None, tmp_path)
    final, partial = resolve_output_targets(settings=config, context={"title": title})
    assert final.suffix == ".zip"
    assert len(final.name) <= 80
    assert _filesystem_length(partial.name) <= 255
    assert _filesystem_length(with_temp_suffix(partial).name) <= 255
    final.write_bytes(b"first")
    again, _ = resolve_output_targets(settings=config, context={"title": title})
    assert again != final
    again.write_bytes(b"second")
    assert final.read_bytes() == b"first"


def test_linux_utf8_limit(monkeypatch):
    import app.core.output_template as module
    monkeypatch.setattr(module, "_filesystem_length", lambda value: len(value.encode("utf-8")))
    result = module._truncate_filename_if_needed("中" * 300 + ".zip", True, 220)
    assert len(result.encode()) <= 223


def test_disabled_truncation_reports_problem_before_download(tmp_path):
    config = OutputTemplateSettings("{title}.zip", "rename", False, 160, None, tmp_path)
    with pytest.raises(OutputTemplateError, match="启用文件名截断"):
        resolve_output_targets(settings=config, context={"title": "x" * 500})


def test_dot_is_not_a_compound_extension():
    result = _truncate_filename_if_needed("Title." + "中" * 300 + ".zip", True, 160)
    assert len(result) <= 160
    assert _filesystem_length(result) <= 223


def test_directory_too_long(tmp_path):
    config = OutputTemplateSettings("./" + "a" * 300 + "/{gid}.zip", "rename", True, 160, None, tmp_path)
    with pytest.raises(OutputTemplateError, match="目录名过长"):
        resolve_output_targets(settings=config, context={"gid": 123})
