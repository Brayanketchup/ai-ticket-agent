"""Install the ticket agent on this PC: write config.json and put the ticket-investigate skill
into your AI coding assistant's skills folder, filled in with this PC's paths. Safe to re-run.

The skills folder is the one your assistant loads SKILL.md playbooks from. Pass it with
--skills-dir, or set AGENT_SKILLS_DIR once.

    python install.py --skills-dir ~/.agent/skills --base-url https://helpdesk.example.com/api/tickets
    python install.py --skills-dir ~/.agent/skills --context-dir D:\\code-map --user-name Alex
    python install.py --test ABC123-45678     # also fetch one ticket to prove it works
    python install.py --uninstall              # remove the installed skill (config and tickets stay)
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "<!-- installed by ticket-agent install.py -->"
SKILL_NAME = "ticket-investigate"


def render_skill(template, cfg, user="the user"):
    tool = (HERE / "ticket_fetch.py").as_posix()
    if cfg.get("context_dir"):
        code_map = (f"Use the code map in `{Path(cfg['context_dir']).as_posix()}` (for example `symbols.tsv` for functions, "
                    "`routes.tsv` for URLs and actions, `tables.tsv` for which files read or write a table; its README explains them) "
                    "before searching the repo.")
    else:
        code_map = "If a code map is available (symbols, routes, tables), use it before searching the repo."
    text = (template.replace("{{TOOL}}", tool)
                    .replace("{{TICKETS_DIR}}", Path(cfg["tickets_dir"]).as_posix())
                    .replace("{{CODE_MAP}}", code_map)
                    .replace("{{USER}}", user))
    head, sep, body = text.partition("\n---\n")
    return head + sep + MARKER + "\n" + body


def main(argv=None):
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is needed.")
    sys.path.insert(0, str(HERE))
    import ticket_fetch

    p = argparse.ArgumentParser(description="Install the ticket agent skill for your AI coding assistant on this PC.")
    p.add_argument("--base-url", help="Ticket service URL")
    p.add_argument("--tickets-dir", help="Where downloaded tickets go (default: tickets/ in this repo)")
    p.add_argument("--context-dir", help="Code map folder (symbols.tsv, routes.tsv, tables.tsv), optional")
    p.add_argument("--user-name", default="the user", help="How the skill refers to you (default: 'the user')")
    p.add_argument("--skills-dir", default=os.environ.get("AGENT_SKILLS_DIR"),
                   help="Your assistant's skills folder (or set AGENT_SKILLS_DIR)")
    p.add_argument("--test", metavar="TICKET", help="Fetch this ticket after installing")
    p.add_argument("--uninstall", action="store_true", help="Remove the installed skill")
    a = p.parse_args(argv)

    if not a.skills_dir:
        p.error("--skills-dir is required (or set AGENT_SKILLS_DIR): the folder your assistant loads skills from")
    target = Path(a.skills_dir).expanduser() / SKILL_NAME
    if a.uninstall:
        f = target / "SKILL.md"
        if f.exists() and MARKER in f.read_text(encoding="utf-8"):
            shutil.rmtree(target)
            print(f"Removed {target}")
        else:
            print(f"Nothing removed: {target} was not installed by this tool.")
        return

    cfg_file = HERE / "config.json"
    existing_cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    for key, val in (("tickets_dir", a.tickets_dir), ("context_dir", a.context_dir), ("base_url", a.base_url)):
        if val:
            existing_cfg[key] = str(Path(val).resolve()) if key.endswith("_dir") else val.rstrip("/")
    cfg_file.write_text(json.dumps(existing_cfg, indent=2) + "\n", encoding="utf-8")
    cfg = ticket_fetch.load_config(cfg_file)
    Path(cfg["tickets_dir"]).mkdir(parents=True, exist_ok=True)

    skill = render_skill((HERE / "skill" / "SKILL.md").read_text(encoding="utf-8"), cfg, a.user_name)
    target.mkdir(parents=True, exist_ok=True)
    installed = target / "SKILL.md"
    if installed.exists() and MARKER not in installed.read_text(encoding="utf-8"):
        shutil.copy2(installed, target / "SKILL.md.before-install")
    installed.write_text(skill, encoding="utf-8", newline="\n")

    print(f"Config:   {cfg_file}")
    print(f"Service:  {cfg['base_url'] or '(not set: add base_url to config.json)'}")
    print(f"Tickets:  {cfg['tickets_dir']}")
    print(f"Code map: {cfg['context_dir'] or '(none)'}")
    print(f"Skill:    {installed}")
    if a.test:
        folder = ticket_fetch.fetch(a.test.strip().upper(), cfg["tickets_dir"], cfg)
        print(f"Test fetch OK: {folder / 'ticket.md'}")
    print("Done. Start a new assistant session and say: look at ticket <number>")


if __name__ == "__main__":
    main()
