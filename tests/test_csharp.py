"""Tests for C# extraction, semantic normalization, and scoped discovery in dryer."""

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


def test_csharp_methods_only_excludes_constructors_properties_operators_and_nested():
    source = """\
namespace Demo;

public class Board {
    public Board() {
        var x = Init(1);
        Use(x);
    }

    public int Value => Compute(1) + Compute(2);
    public int Auto { get; set; }
    public int Prop {
        get { return Compute(1); }
        set { Store(value); }
    }
    public static int operator +(Board a, Board b) {
        return a.Value + b.Value;
    }

    public int Alpha(int value) {
        int Local(int z) { return z + 1; }
        var fn = (int k) => k * 2;
        var mapped = Map<int>(Local(value));
        return fn(mapped) + 1;
    }

    public int ExprMethod(int value) => Map<int>(value) + 1;
}
"""
    entries, warning = entries_in_source("csharp", source, "Board.cs", "Board.cs")
    assert warning is None
    assert [(e.start_line, e.end_line) for e in entries] == [(19, 24), (26, 26)]


def test_csharp_overloads_and_partials_keep_distinct_locations(tmp_path):
    _write(
        tmp_path,
        "src/Board.cs",
        """\
namespace Demo;
public partial class Board {
    public int Process(int a) {
        var s = Normalize(a);
        var t = Validate(s);
        var u = Transform(t);
        return Finalize(u);
    }
    public int Process(string text) {
        var s = Normalize(text);
        var t = Validate(s);
        var u = Transform(t);
        return Finalize(u);
    }
}
""",
    )
    _write(
        tmp_path,
        "src/Board.Part.cs",
        """\
namespace Demo;
public partial class Board {
    public int Reset(int seed) {
        var s = Normalize(seed);
        var t = Validate(s);
        var u = Transform(t);
        return Finalize(u);
    }
}
""",
    )
    assert run(["--root", str(tmp_path)]) == 0
    edn = (tmp_path / ".metrics" / "dry.edn").read_text(encoding="utf-8")
    assert "src/Board.cs" in edn
    assert "src/Board.Part.cs" in edn


def test_csharp_optional_calls_generic_and_qualified_callees_stay_distinct(tmp_path):
    # Default-size CLI fixture: x?.Approve() vs x?.Reject() MUST NOT score 1.0
    _write(
        tmp_path,
        "src/A.cs",
        """\
namespace Demo;
public class WorkflowA {
    public int Run(Order item, Handler gate) {
        var step = gate?.Approve(item);
        var next = new global::Acme.Validator<int>(step) { Mode = 1 };
        var checkedVal = next.Check(item);
        return checkedVal + 1;
    }
}
""",
    )
    _write(
        tmp_path,
        "src/B.cs",
        """\
namespace Demo;
public class WorkflowB {
    public int Run(Order order, Handler svc) {
        var step = svc?.Reject(order);
        var next = new global::Acme.Validator<int>(step) { Mode = 2 };
        var checkedVal = next.Check(order);
        return checkedVal + 2;
    }
}
""",
    )
    _write(
        tmp_path,
        "src/C.cs",
        """\
namespace Demo;
public class WorkflowC {
    public int Run(Order req, Handler pipe) {
        var first = pipe?.Approve(req);
        var other = new global::Acme.Validator<int>(first) { Mode = 9 };
        var result = other.Check(req);
        return result + 9;
    }
}
""",
    )
    entries_a, _ = entries_in_source("csharp", (tmp_path / "src/A.cs").read_text(), "src/A.cs", "src/A.cs")
    entries_b, _ = entries_in_source("csharp", (tmp_path / "src/B.cs").read_text(), "src/B.cs", "src/B.cs")
    entries_c, _ = entries_in_source("csharp", (tmp_path / "src/C.cs").read_text(), "src/C.cs", "src/C.cs")

    pair_ab = find_duplicates(entries_a + entries_b, threshold=0.0)
    assert len(pair_ab) == 1
    assert pair_ab[0].score < 1.0

    pair_ac = find_duplicates(entries_a + entries_c, threshold=0.99)
    assert len(pair_ac) == 1
    assert pair_ac[0].score == 1.0

    # Ordinary vs null-conditional access remain distinct
    direct = """\
namespace Demo;
class D {
    void Go(Handler h, Order o) {
        var x = h.Approve(o);
        Commit(x);
    }
}
"""
    opt = """\
namespace Demo;
class O {
    void Go(Handler h, Order o) {
        var x = h?.Approve(o);
        Commit(x);
    }
}
"""
    ed, _ = entries_in_source("csharp", direct, "D.cs", "D.cs")
    eo, _ = entries_in_source("csharp", opt, "O.cs", "O.cs")
    p = find_duplicates(ed + eo, threshold=0.0)
    assert len(p) == 1 and p[0].score < 1.0


def test_csharp_scoped_discovery_preserves_other_languages(tmp_path):
    # C# production project with obj/bin outputs and generated files
    _write(tmp_path, "App/App.csproj", '<Project Sdk="Microsoft.NET.Sdk" />\n')
    prod_cs = _write(tmp_path, "App/Calc.cs", "class Calc { int F(int x) { return x + 1; } }\n")
    _write(tmp_path, "App/obj/Debug/Calc.g.cs", "class Calc { int F(int x) { return x + 1; } }\n")
    _write(tmp_path, "App/bin/Debug/Copy.cs", "class Calc { int F(int x) { return x + 1; } }\n")
    _write(tmp_path, "App/Form1.Designer.cs", "class Form1 { void Init() { } }\n")
    _write(tmp_path, "App/Auto.generated.cs", "class Auto { void Init() { } }\n")

    # C# test project without "Tests" in folder name, detected via .csproj XML
    _write(
        tmp_path,
        "Checks/Checks.csproj",
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup></Project>\n',
    )
    _write(tmp_path, "Checks/CalcCheck.cs", "class CalcCheck { void T() { } }\n")

    # Non-C# production files in bin/ and .Specs must NOT be globally excluded!
    rust_bin = _write(tmp_path, "crate/src/bin/main.rs", "fn main() { println!(\"hi\"); }\n")
    py_bin = _write(tmp_path, "bin/helper.py", "def help_me(x):\n    return x + 1\n")
    ps_bin = _write(tmp_path, "bin/Helper.ps1", "function Get-HelpData { param($x) return $x }\n")
    go_specs = _write(tmp_path, "Tools.Specs/run.go", "package specs\nfunc Run() int { return 1 }\n")

    assert language_of("App/Form1.Designer.cs") is None
    assert language_of("App/Auto.g.i.cs") is None
    assert not is_test_file(rust_bin)
    assert not is_test_file(py_bin)
    assert not is_test_file(ps_bin)
    assert not is_test_file(go_specs)

    found = {p.resolve() for p in iter_source_files([tmp_path])}
    assert prod_cs.resolve() in found
    assert rust_bin.resolve() in found
    assert py_bin.resolve() in found
    assert ps_bin.resolve() in found
    assert go_specs.resolve() in found
    assert all("Checks" not in p.parts for p in found)
    assert all("obj" not in p.parts for p in found)
    assert all(p.name != "Copy.cs" for p in found)


def test_csharp_malformed_method_skips_with_warning_preserving_siblings():
    source = """\
namespace Demo;
public class Mix {
    public int Good(int x) {
        var a = Load(x);
        var b = Transform(a);
        return b + 1;
    }
    public int Broken(int x) {
        return ((( ;
    }
}
"""
    entries, warning = entries_in_source("csharp", source, "Mix.cs", "Mix.cs")
    assert warning is not None
    assert len(entries) == 1
    assert entries[0].start_line == 3
