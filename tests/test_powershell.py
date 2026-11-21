"""Tests for PowerShell extraction, operator preservation, and discovery in dryer."""

from pathlib import Path

from dryer.cli import run
from dryer.discover import is_test_file, iter_source_files, language_of
from dryer.extract import entries_in_source
from dryer.scan import find_duplicates


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_powershell_opposite_operators_do_not_match_1_0(tmp_path):
    # Default-size CLI fixtures reproducing F6 (lost operators)
    _write(
        tmp_path,
        "src/Greater.ps1",
        """\
function Test-ThresholdA {
    param($score, $limit, $flag)
    if ($score -gt $limit -and $flag -eq $true) {
        $adjusted = $score + 10
        Write-Output $adjusted
        return $adjusted
    }
    Write-Warning "below"
    return 0
}
""",
    )
    _write(
        tmp_path,
        "src/Less.ps1",
        """\
function Test-ThresholdB {
    param($value, $bound, $ok)
    if ($value -lt $bound -or $ok -ne $false) {
        $next = $value + 20
        Write-Output $next
        return $next
    }
    Write-Warning "above"
    return 0
}
""",
    )
    # Run via real CLI at default min-lines/min-nodes and threshold 0.99
    assert run(["--root", str(tmp_path), "--threshold", "0.99"]) == 0
    edn = (tmp_path / ".metrics" / "dry.edn").read_text(encoding="utf-8")
    assert edn == "{:candidates []}\n"


def test_powershell_case_folding_vs_case_sensitive_operators():
    upper = """\
function script:Check-Alpha {
    param($x, $y)
    if ($x -GT $y -AND $true) {
        WRITE-OUTPUT ($x + 1)
        return $x
    }
    return 0
}
"""
    lower = """\
function Check-Beta {
    param($a, $b)
    if ($a -gt $b -and $true) {
        write-output ($a + 2)
        return $a
    }
    return 0
}
"""
    ceq = """\
function Check-Exact {
    param($a, $b)
    if ($a -ceq $b -and $true) {
        write-output ($a + 2)
        return $a
    }
    return 0
}
"""
    ieq = """\
function Check-Insensitive {
    param($a, $b)
    if ($a -ieq $b -and $true) {
        write-output ($a + 2)
        return $a
    }
    return 0
}
"""
    eu, _ = entries_in_source("powershell", upper, "u.ps1", "u.ps1")
    el, _ = entries_in_source("powershell", lower, "l.ps1", "l.ps1")
    ec, _ = entries_in_source("powershell", ceq, "c.ps1", "c.ps1")
    ei, _ = entries_in_source("powershell", ieq, "i.ps1", "i.ps1")

    same = find_duplicates(eu + el, threshold=0.99)
    assert len(same) == 1 and same[0].score == 1.0

    diff = find_duplicates(ec + ei, threshold=0.0)
    assert len(diff) == 1 and diff[0].score < 1.0


def test_powershell_different_commands_and_class_methods():
    src = """\
class Runner {
    [int] Approve([int]$n) {
        $res = Invoke-Approve $n
        Write-Output $res
        return $res + 1
    }
    [int] Reject([int]$m) {
        $out = Invoke-Reject $m
        Write-Output $out
        return $out + 2
    }
}
"""
    entries, warning = entries_in_source("powershell", src, "Runner.psm1", "Runner.psm1")
    assert warning is None
    assert len(entries) == 2
    pairs = find_duplicates(entries, threshold=0.0)
    assert len(pairs) == 1 and pairs[0].score < 1.0


def test_powershell_discovery_skips_pester_tests_keeps_bin(tmp_path):
    prod = _write(tmp_path, "bin/Helper.ps1", "function Get-A { return 1 }\n")
    mod = _write(tmp_path, "src/Core.psm1", "function Get-B { return 2 }\n")
    _write(tmp_path, "src/Core.Tests.ps1", "Describe 'Core' { It 'works' {} }\n")
    _write(tmp_path, "src/Core.tests.ps1", "Describe 'Core2' { It 'works' {} }\n")

    assert language_of(prod) == "powershell"
    assert language_of(mod) == "powershell"
    assert is_test_file("src/Core.Tests.ps1")
    assert not is_test_file(prod)

    found = {p.resolve() for p in iter_source_files([tmp_path])}
    assert prod.resolve() in found
    assert mod.resolve() in found
    assert all("Tests" not in p.name and "tests" not in p.name for p in found)
