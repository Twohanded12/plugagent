import sys
from pathlib import Path

if __package__ in (None, ""):  # executed as `python3 scripts/pa` — make `pa` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: pa <capture|memory|distill|wiki|raw|vault|config|status> ...")
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "capture":
        try:
            from pa import capture, config
            if args[:1] == ["--transcript"] and len(args) == 2:
                capture.run(args[1])
        except Exception as e:  # capture must never break the session
            try:
                from pa import config as _c
                with open(_c.state_dir() / "errors.log", "a", encoding="utf-8") as f:
                    import datetime
                    f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} capture: {e!r}\n")
            except Exception:
                import sys as _s
                print(f"pa capture error: {e!r}", file=_s.stderr)
        return 0
    if cmd == "memory":
        try:
            from pa import memory
            if args[:1] == ["list"]:
                memory.rebuild_index()
                print(memory.hot_index_text())
                return 0
            if args[:1] == ["show"] and len(args) == 2:
                print(memory.show(args[1]))
                return 0
            if args[:1] == ["show"] and len(args) == 4 and args[2] == "--from":
                print(memory.show(args[1], member=args[3]))
                return 0
            if args[:1] == ["add"] and len(args) == 5:
                memory.add(args[1], args[2], args[3], args[4])
                print(f"saved card {args[1]!r}")
                return 0
            if args[:1] == ["recall"] and len(args) == 2:
                for h in memory.recall(args[1]):
                    who = f" (team: {h['member']})" if h.get("member") else ""
                    print(f"## {h['name']} — {h['description']}{who}\n{h['body']}\n")
                return 0
            if args[:1] == ["forget"] and len(args) == 2:
                ok = memory.forget(args[1])
                print("forgotten" if ok else f"no card named {args[1]!r}")
                return 0
            print("usage: pa memory list [--hot] | show <name> [--from <member>] | "
                  "add <name> <description> <type> <body> | recall <kw> | forget <name>")
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "distill":
        try:
            from pa import distill
            if args[:1] == ["pending"]:
                for p in distill.pending():
                    print(p.name)
                return 0
            if args[:1] == ["advance"] and args[1:2] == ["--to"] and len(args) == 3:
                distill.advance(args[2])
                return 0
            print("usage: pa distill pending | pa distill advance --to <raw-filename>")
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "wiki":
        try:
            from pa import distill
            if args[:1] == ["put"] and len(args) == 2:
                page = distill.put_from_stdin(args[1])
                print(f"wrote {page}")
                return 0
            print("usage: pa wiki put <relpath>   (content on stdin)")
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "raw":
        try:
            from pa import distill
            if args[:1] == ["forget"] and len(args) == 2:
                ok, n = distill.raw_forget(args[1])
                if ok:
                    print("deleted")
                    return 0
                if n == 0:
                    print(f"no match for {args[1]!r} — nothing deleted")
                else:
                    print(f"{n} matches for {args[1]!r} — be more specific")
                return 1
            print("usage: pa raw forget <session-id-fragment>")
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "status":
        try:
            from pa import status
            print(status.full() if args[:1] == ["--full"] else status.one_line())
            return 0
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "team":
        _TEAM_USAGE = ("usage: pa team init <name> --repo <url> --as <member> | "
                      "join <url> --key <file> --as <member> | "
                      "sync [--force] [--team T] | share <wiki-relpath> [--team T] | "
                      "rekey [--team T] | rekey-accept --key <file> [--team T] | "
                      "privacy on [--team T] | privacy-accept --fnkey <file> [--team T] | "
                      "share-card <name> [--confirm-schema-bump] [--team T] | "
                      "unshare-card <name> [--team T] | memory on|off [--team T] | "
                      "status")

        def _flag(args, name):
            if name not in args:
                return None
            i = args.index(name)
            if i + 1 >= len(args):
                raise Exception(f"{name} needs a value")
            return args[i + 1]

        try:
            from pa import team
            if args[:1] == ["init"] and len(args) == 6 and args[2] == "--repo" and args[4] == "--as":
                print(team.init_team(args[1], args[3], args[5]))
                return 0
            if args[:1] == ["join"] and len(args) == 6 and args[2] == "--key" and args[4] == "--as":
                from pathlib import Path as _P
                print(team.join_team(args[1], _P(args[3]).expanduser(), args[5]))
                return 0
            if args[:1] == ["sync"]:
                name = _flag(args, "--team")
                print(team.sync(team.resolve_team(name), force="--force" in args))
                return 0
            if args[:1] == ["share"] and len(args) >= 2:
                if args[1].startswith("--"):
                    print(_TEAM_USAGE)
                    return 1
                name = _flag(args, "--team")
                print(team.share(team.resolve_team(name), args[1]))
                return 0
            if args[:1] == ["rekey-accept"] and "--key" in args:
                from pathlib import Path as _P
                key = _P(_flag(args, "--key")).expanduser()
                name = _flag(args, "--team")
                print(team.rekey_accept(team.resolve_team(name), key))
                return 0
            if args[:1] == ["rekey"]:
                name = _flag(args, "--team")
                print(team.rekey(team.resolve_team(name)))
                return 0
            if args[:2] == ["privacy", "on"]:
                name = _flag(args, "--team")
                print(team.privacy_on(team.resolve_team(name)))
                return 0
            if args[:1] == ["privacy-accept"] and "--fnkey" in args:
                from pathlib import Path as _P
                fnkey = _P(_flag(args, "--fnkey")).expanduser()
                name = _flag(args, "--team")
                print(team.privacy_accept(team.resolve_team(name), fnkey))
                return 0
            if args[:1] == ["share-card"] and len(args) >= 2 and not args[1].startswith("--"):
                name = _flag(args, "--team")
                print(team.share_card(team.resolve_team(name), args[1],
                                      confirm_schema_bump="--confirm-schema-bump" in args))
                return 0
            if args[:1] == ["unshare-card"] and len(args) >= 2 and not args[1].startswith("--"):
                name = _flag(args, "--team")
                print(team.unshare_card(team.resolve_team(name), args[1]))
                return 0
            if args[:2] in (["memory", "on"], ["memory", "off"]):
                name = _flag(args, "--team")
                print(team.set_team_memory(team.resolve_team(name), args[1] == "on"))
                return 0
            if args[:1] == ["status"]:
                print(team.status_report())
                return 0
            print(_TEAM_USAGE)
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    if cmd == "vault" and args == ["reinit"]:
        from pa import config
        config.vault_reinit()
        print("vault markers cleared — next write will re-create the vault")
        return 0
    if cmd == "config":
        try:
            from pa import config
            if args[:1] == ["get"] and len(args) == 2:
                print(config.load().get(args[1]))
                return 0
            if args[:1] == ["set"] and len(args) == 3:
                config.set_value(args[1], args[2])
                return 0
            print("usage: pa config get <key> | pa config set <key> <value>")
            return 1
        except Exception as e:
            print(f"pa: {e}")
            return 1
    print(f"pa: unknown command {cmd!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
