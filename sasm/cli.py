"""Command-line interface (DESIGN §8).

  python -m sasm emit  <file.sasm>            # print .s to stdout
  python -m sasm build <file.sasm> [-o x.s]   # emit .s to a file (or stdout)
  python -m sasm facts <file.sasm> <entity>   # dump every fact about an entity
"""

from __future__ import annotations

import argparse
import sys

from .emit import EmitError, emit
from .format import format_program
from .parser import ParseError, parse
from .validate import validate


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sasm")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_emit = sub.add_parser("emit", help="print emitted .s to stdout")
    p_emit.add_argument("file")

    p_build = sub.add_parser("build", help="emit .s to a file")
    p_build.add_argument("file")
    p_build.add_argument("-o", "--output")
    p_build.add_argument("--force", action="store_true",
                         help="emit even if validation reports errors")

    p_check = sub.add_parser("check", help="parse + validate, print diagnostics")
    p_check.add_argument("file")

    p_fmt = sub.add_parser("fmt", help="canonical-format a .sasm file")
    p_fmt.add_argument("file")
    p_fmt.add_argument("-i", "--in-place", action="store_true",
                       help="rewrite the file instead of printing to stdout")

    p_facts = sub.add_parser("facts", help="dump facts about an entity")
    p_facts.add_argument("file")
    p_facts.add_argument("entity")

    p_exec = sub.add_parser(
        "exec", help="execute the facts in the taint-tracking interpreter "
                     "(DESIGN §19): runs the program and checks the semantic "
                     "facts dynamically (R-* diagnostics)")
    p_exec.add_argument("file")
    p_exec.add_argument("function", nargs="?",
                        help="function handle/symbol to call (omit with --start)")
    p_exec.add_argument("args", nargs="*",
                        help="integer args; [1,2,3] allocates an Int64 array "
                             "and passes its address")
    p_exec.add_argument("--start", action="store_true",
                        help="run the program entry (_start style)")
    p_exec.add_argument("--expect", type=int,
                        help="fail unless the result / exit code equals this")
    p_exec.add_argument("--coverage", action="store_true",
                        help="print the trace-scope coverage report (§18.1)")

    args = ap.parse_args(argv)
    # keep UTF-8 output (Windows consoles default to cp1252 and mangle em-dashes)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    try:
        prog = parse(_read(args.file))
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1

    if args.cmd == "fmt":
        out = format_program(prog)
        if args.in_place:
            with open(args.file, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
        else:
            sys.stdout.buffer.write(out.encode("utf-8"))
        return 0

    if args.cmd == "check":
        diags = validate(prog)
        for d in diags:
            print(d)
        errors = sum(1 for d in diags if d.severity == "error")
        warns = len(diags) - errors
        print(f"{errors} error(s), {warns} warning(s)", file=sys.stderr)
        return 1 if errors else 0

    if args.cmd in ("emit", "build"):
        if args.cmd == "build" and not getattr(args, "force", False):
            errs = [d for d in validate(prog) if d.severity == "error"]
            if errs:
                for d in errs:
                    print(d, file=sys.stderr)
                print(f"refusing to emit: {len(errs)} error(s) (use --force)",
                      file=sys.stderr)
                return 1
        try:
            out = emit(prog)
        except EmitError as e:
            print(f"emit error: {e}", file=sys.stderr)
            return 1
        if args.cmd == "build" and args.output:
            with open(args.output, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
        else:
            # raw bytes: keep LF on Windows (text-mode stdout would add CRs),
            # which is what assemblers expect for .s
            sys.stdout.buffer.write(out.encode("utf-8"))
        return 0

    if args.cmd == "exec":
        from .interp import ExecError, Machine
        m = Machine(prog)
        try:
            if args.start:
                result = m.run_start()
                label = "exit"
            else:
                if not args.function:
                    print("exec: need a function name or --start", file=sys.stderr)
                    return 2
                call_args = []
                for a in args.args:
                    if a.startswith("["):
                        vals = [int(x) for x in a.strip("[]").split(",") if x]
                        call_args.append(m.alloc_int64_array(vals))
                    else:
                        call_args.append(int(a))
                result = m.call(args.function, call_args)
                label = "result"
        except ExecError as e:
            print(f"exec error: {e}", file=sys.stderr)
            return 1
        if m.stdout:
            sys.stdout.buffer.write(bytes(m.stdout))
        print(f"{label}: {result}")
        for d in m.diags:
            print(d)
        if args.coverage:
            cov = m.coverage()
            print(f"coverage: blocks-not-executed={cov['blocksNotExecuted'] or 'none'} "
                  f"reads-confirmed={cov['readsConfirmed']} "
                  f"reads-unconfirmed={cov['readsUnconfirmed'] or 'none'} "
                  f"liveOut-checked={cov['liveOutChecked']} steps={cov['steps']}")
        errors = sum(1 for d in m.diags if d.severity == "error")
        if args.expect is not None and result != args.expect:
            print(f"EXPECT FAILED: {label} {result} != {args.expect}",
                  file=sys.stderr)
            return 1
        return 1 if errors else 0

    if args.cmd == "facts":
        ent = prog.get(args.entity)
        if ent is None:
            print(f"no such entity: {args.entity}", file=sys.stderr)
            return 1
        print(f"{ent.name} is {ent.type}")
        for pred, rows in ent.facts.items():
            for row in rows:
                print(f"  {pred} {' '.join(row)}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
