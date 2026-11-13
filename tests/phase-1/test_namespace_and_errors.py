"""US1: namespace handling, errors, atomic/deterministic writing (T006)."""

import os

import pytest

from saft_reader import NS, SaftReaderError, main, read_saft, write_saft_data


def _rewrite(sample_path, tmp_path, name, transform):
    with open(sample_path, encoding="utf-8") as fh:
        text = transform(fh.read())
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _without_source(data):
    return {**data, "summary": {k: v for k, v in data["summary"].items() if k != "source_file"}}


def test_prefix_invariance(sample_path, tmp_path):
    original = _without_source(read_saft(sample_path))
    default_ns = _rewrite(sample_path, tmp_path, "default.xml", lambda t: t.replace(
        f'xmlns:n1="{NS}"', f'xmlns="{NS}"').replace("<n1:", "<").replace("</n1:", "</"))
    ns0 = _rewrite(sample_path, tmp_path, "ns0.xml", lambda t: t.replace(
        "xmlns:n1=", "xmlns:ns0=").replace("<n1:", "<ns0:").replace("</n1:", "</ns0:"))
    assert _without_source(read_saft(default_ns)) == original
    assert _without_source(read_saft(ns0)) == original


def test_wrong_namespace_is_exit_2(tmp_path):
    path = tmp_path / "pt.xml"
    path.write_text('<AuditFile xmlns="urn:OECD:StandardAuditFile-Tax:PT_1.04_01"/>',
                    encoding="utf-8")
    with pytest.raises(SaftReaderError) as exc:
        read_saft(str(path))
    assert exc.value.exit_code == 2


def test_wrong_root_is_exit_2(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text(f'<Document xmlns="{NS}"/>', encoding="utf-8")
    with pytest.raises(SaftReaderError) as exc:
        read_saft(str(path))
    assert exc.value.exit_code == 2


def test_not_xml_is_exit_1(tmp_path):
    path = tmp_path / "junk.xml"
    path.write_text("this is not xml", encoding="utf-8")
    with pytest.raises(SaftReaderError) as exc:
        read_saft(str(path))
    assert exc.value.exit_code == 1


def test_missing_file_is_exit_1(tmp_path):
    with pytest.raises(SaftReaderError) as exc:
        read_saft(str(tmp_path / "nope.xml"))
    assert exc.value.exit_code == 1


def test_failed_run_leaves_existing_output_untouched(tmp_path, capsys):
    out = tmp_path / "saft_data.json"
    out.write_bytes(b'{"previous": "good output"}\n')
    bad = tmp_path / "pt.xml"
    bad.write_text('<AuditFile xmlns="urn:other"/>', encoding="utf-8")
    assert main([str(bad), "-o", str(out)]) == 2
    assert out.read_bytes() == b'{"previous": "good output"}\n'
    assert "error:" in capsys.readouterr().err


def test_other_version_parses_with_warning(sample_path, tmp_path):
    old = _rewrite(sample_path, tmp_path, "v110.xml", lambda t: t.replace(
        "<n1:AuditFileVersion>1.30<", "<n1:AuditFileVersion>1.10<"))
    data = read_saft(old)
    assert data["summary"]["saft_version"] == "1.10"
    assert any("1.10" in w for w in data["summary"]["warnings"])
    assert data["accounts"]


def test_write_is_deterministic_and_atomic(sample_path, tmp_path):
    data = read_saft(sample_path)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_saft_data(data, str(first))
    write_saft_data(read_saft(sample_path), str(second))
    assert first.read_bytes() == second.read_bytes()
    assert "Bespisning/Mat" in first.read_text(encoding="utf-8")
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]


def test_cli_success(sample_path, out_path, capsys):
    assert main([sample_path, "-o", out_path]) == 0
    assert os.path.isfile(out_path)
    assert "accounts" in capsys.readouterr().out
