"""The judge's fixed rules (plan 30.2): the first stage of the Auto mode's judge.

`classify(call, folder) -> Verdict(verdict, reason, rule)`, where `verdict` is:
- `allow`: clearly safe (read-only commands and test runners on a known list, each with its own list of options;
  edits inside an Edit folder; documentation on a known host). Never a command that runs with the internet on
  (`args.network`): what it reads it could send, so the model decides;
- `ask`: clearly needs the user (rm -rf outside build folders, `curl … | sh`, writes to dotfiles, history rewriting,
  killing processes, credentials, anything on the host, sudo);
- `unsure`: the rules can't tell; the judge's model decides (plan 30.3), with `reason` saying why.

`call` is `{tool, args, estimate?}`: `tool` a tool name (`workspace_run`, `workspace_edit`, `web_fetch`, …), `args`
its arguments, `estimate` `{seconds, memory_gb, memory_share}` for a GPU job. `folder` is the workspace folder the
call runs in: `{path, level}` with level read | edit | run | run_net. A shell command is split with `shell.parse`
and every simple command in it is judged (`a && b`, pipes, `$(…)`, `bash -c`, `env`, `xargs` and other wrappers):
one `ask` makes the whole call ask, else one `unsure` makes it unsure. The rules never deny: the hard limits and
the folder's level (Phase 27) refuse; the worst a rule does is ask.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import posixpath
import re
from typing import Any, NamedTuple
from urllib.parse import parse_qsl, urlsplit

from .shell import SUB

LEVELS = ("read", "edit", "run", "run_net")
LONG_JOB_S = 300                     # a GPU job longer than this is in the judge's scope ("a few minutes")
LONG_JOB_SHARE = 0.5                 # … or one that needs more than this share of the memory
HUGE_JOB_S = 4 * 3600                # past this the rules ask
HUGE_JOB_GB = 96
MAX_COMMAND = 4000
HIJACK_ENV_RE = re.compile(r"^(LD_PRELOAD|LD_LIBRARY_PATH|LD_AUDIT|PYTHONSTARTUP|PYTHONPATH|BASH_ENV|ENV|PROMPT_COMMAND"
                           r"|GIT_SSH_COMMAND|GIT_SSH|GIT_EXTERNAL_DIFF|GIT_ASKPASS|SSH_ASKPASS|PAGER|GIT_PAGER|EDITOR"
                           r"|VISUAL|NODE_OPTIONS|PERL5OPT|RUBYOPT)=")
# Variables that point a tool at other programs, configs or search paths (rg's config can add --pre, PATH picks the
# program that runs): the rules can't see what runs, so the model decides.
CONFIG_ENV_RE = re.compile(r"^(PATH|HOME|XDG_\w+|ZDOTDIR|SHELL|IFS|PS4|RIPGREP_CONFIG_PATH|LESS\w*|TAR_OPTIONS"
                           r"|MAKEFLAGS|MFLAGS|GNUMAKEFLAGS|MAKEFILES|BAT_\w+|MANPAGER|GIT_\w+|NPM_CONFIG_\w+|YARN_\w+"
                           r"|PERL5?LIB|RUBYLIB|NODE_PATH|PYTEST_ADDOPTS|PYTEST_PLUGINS|DYLD_\w+|LD_\w+|GCONV_PATH"
                           r"|CARGO_\w+|RUSTC\w*|RUSTFLAGS|RUSTDOCFLAGS|GOFLAGS|GOROOT|GOPATH|GOTOOLCHAIN|CC|CXX|CPP"
                           r"|LD|AR|CFLAGS|CXXFLAGS|LDFLAGS|PYTHONHOME|PYTHONUSERBASE|VIRTUAL_ENV|UV_\w+|PIP_\w+"
                           r"|TOX_\w+|BROWSER)=", re.I)


class Verdict(NamedTuple):
    verdict: str                     # allow | ask | unsure
    reason: str
    rule: str


def allow(reason: str, rule: str) -> Verdict:
    return Verdict("allow", reason, rule)


def ask(reason: str, rule: str) -> Verdict:
    return Verdict("ask", reason, rule)


def unsure(reason: str, rule: str) -> Verdict:
    return Verdict("unsure", reason, rule)


def combine(verdicts: list[Verdict]) -> Verdict:
    """The strictest: any ask, else any unsure, else allow (the first of each kind gives the reason)."""
    for kind in ("ask", "unsure"):
        for v in verdicts:
            if v.verdict == kind:
                return v
    return verdicts[0] if verdicts else ask("nothing to run", "empty")


SECRET_RE = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|hf_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|authorization:\s*(?:bearer|basic)\s+\S+"
    r"|(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*['\"]?[^\s'\"$]{6,}"
    r"|--(?:password|token|api-key)[= ]\S+)", re.IGNORECASE)
SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\.[\w.-]+)?|\.envrc|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?"
    r"|[^/]*\.(pem|key|p12|pfx|kdbx)|[^/]*credentials?[^/]*|secrets?(\.[\w]+)?|shadow|gshadow|\.htpasswd)$"
    r"|(^|/)\.(ssh|aws|gnupg|kube|docker|password-store)(/|$)", re.IGNORECASE)
# Paths whose change runs code later or changes how tools behave: never written without asking.
SENSITIVE_WRITE_RE = re.compile(
    r"(^|/)(\.git(/|$)|\.github/workflows/|\.gitlab-ci\.yml$|\.circleci/|\.husky/|\.pre-commit-config\.yaml$"
    r"|\.vscode/(tasks|settings|launch)\.json$|\.idea/|\.bashrc$|\.bash_profile$|\.profile$|\.zshrc$|\.zprofile$"
    r"|\.bash_logout$|\.inputrc$|\.gitconfig$|\.config/|\.local/|\.cache/|\.ssh/|\.gnupg/|\.aws/|\.kube/|\.docker/"
    r"|\.netrc$|\.npmrc$|\.pypirc$|\.envrc$|\.env(\.[\w.-]+)?$|\.git-credentials$|\.mcp\.json$|\.claude/|\.cursor/)")
DOCS_HOSTS = {"docs.python.org", "developer.mozilla.org", "pypi.org", "en.wikipedia.org", "docs.rs", "crates.io",
              "pkg.go.dev", "www.npmjs.com", "nodejs.org", "docs.github.com", "learn.microsoft.com",
              "docs.pytest.org", "fastapi.tiangolo.com", "docs.pydantic.dev", "huggingface.co",
              "www.rust-lang.org", "doc.rust-lang.org", "go.dev", "man7.org", "www.postgresql.org", "sqlite.org"}
# Exact hosts only: a multi-tenant domain (readthedocs.io, github.io, netlify.app …) serves whoever signs up, so a page
# there could be an attacker's server; the model decides those.
MAX_DOCS_PATH = 300
ENCODED_RE = re.compile(r"[A-Za-z0-9+/=_-]{40,}")         # a path segment long enough to carry a secret
SLUG_RE = re.compile(r"[a-z0-9]{1,24}(?:[-_.][a-z0-9]{1,24})+")   # words-with-hyphens, as page names are
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DOT_SECRETS = (".env", ".env.local", ".envrc", ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd", ".ssh",
               ".aws", ".gnupg", ".kube", ".docker", ".password-store")
NAMED_SECRETS = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "secrets", "secret", "shadow", "key.pem",
                 "server.key", "cert.p12", "vault.kdbx")
# The options an allowed tool may take, as (short switches, short options that take a value, long options): a long
# name ending in "=" takes a value, "==" two; "#" lets digits through (head -20). Any other option falls through to
# the model: the lists leave out whatever runs a program (rg --pre, fd -x, sort --compress-program, bat --pager),
# writes a file (sort -o, tree -o, yq -i, xxd -r), sets the clock or the host name, or reaches a remote.
OPTS: dict[str, tuple[str, str, str]] = {
    "ls": ("aAbBcCdDfFgGhHiklLmnNopqQrRsStuUvxXZ1", "ITw", "all almost-all author escape block-size= ignore-backups "
           "color classify file-type format= full-time group-directories-first no-group human-readable si dereference "
           "dereference-command-line hide= ignore= indicator-style= inode kibibytes literal numeric-uid-gid "
           "quote-name quoting-style= reverse recursive size sort= time= time-style= tabsize= width= directory zero"),
    "cat": ("AbeEnstTuv", "", "show-all number-nonblank show-ends number squeeze-blank show-tabs show-nonprinting"),
    "head": ("qvz#", "cn", "bytes= lines= quiet silent verbose zero-terminated"),
    "tail": ("fFqvz#", "cns", "bytes= follow lines= quiet silent verbose retry pid= sleep-interval= zero-terminated"),
    "less": ("NRSFXi", "", ""), "more": ("", "", ""),
    "wc": ("clmwL", "", "bytes chars lines words max-line-length total="),
    "grep": ("abcEFGhHiIlLnoPqrRsTuUvVwxyzZ#", "ABCefmdD", "include= exclude= exclude-dir= color colour recursive "
             "dereference-recursive ignore-case no-ignore-case line-number count files-with-matches "
             "files-without-match word-regexp line-regexp invert-match only-matching quiet silent no-filename "
             "with-filename max-count= after-context= before-context= context= regexp= file= fixed-strings "
             "extended-regexp perl-regexp basic-regexp binary-files= text null null-data label= byte-offset "
             "no-messages devices= directories= initial-tab line-buffered"),
    "rg": ("abcFHhiIlLnNopPqsSuUvVwx0.", "ABCefgtTmMrEdj", "hidden no-ignore no-ignore-vcs no-ignore-dot "
           "no-ignore-parent glob= iglob= type= type-not= files files-with-matches files-without-match count "
           "count-matches json vimgrep max-depth= max-count= fixed-strings ignore-case smart-case case-sensitive "
           "word-regexp line-regexp line-number no-line-number no-heading heading with-filename no-filename color= "
           "colors= context= after-context= before-context= replace= multiline multiline-dotall follow sort= sortr= "
           "stats trim max-filesize= no-messages only-matching invert-match type-list column no-column null pcre2 "
           "engine= unrestricted no-config text binary passthru byte-offset max-columns= max-columns-preview quiet "
           "regexp= file= threads= encoding= crlf null-data line-buffered block-buffered context-separator= "
           "field-match-separator= path-separator= version help"),
    "ag": ("acfHilLnQsStuUvw0.", "ABCmGgW", "hidden ignore= ignore-case case-sensitive smart-case literal "
           "word-regexp files-with-matches files-without-matches count context= after= before= depth= max-count= "
           "nocolor color nogroup group column follow vimgrep noheading only-matching invert-match stats "
           "skip-vcs-ignores unrestricted all-types search-binary"),
    "fd": ("HIsiugFalLp0q1", "dteESjco", "hidden no-ignore no-ignore-vcs unrestricted case-sensitive ignore-case glob "
           "regex fixed-strings absolute-path list-details follow full-path print0 max-depth= min-depth= exact-depth= "
           "type= extension= exclude= size= changed-within= changed-before= owner= max-results= color= threads= "
           "strip-cwd-prefix base-directory= search-path= prune one-file-system quiet show-errors format="),
    "tree": ("adfilsuhgpDFQNqrtvUcCnAxJ", "LPI", "dirsfirst filesfirst noreport gitignore charset= du prune matchdirs "
             "filelimit= sort= ignore-case timefmt= si inodes device version help"),
    "sort": ("bdfgiMhnRrVcCsuzm", "ktS", "key= field-separator= numeric-sort human-numeric-sort general-numeric-sort "
             "month-sort random-sort version-sort reverse unique ignore-case ignore-leading-blanks dictionary-order "
             "ignore-nonprinting stable check zero-terminated buffer-size= parallel= merge debug sort="),
    "uniq": ("cdDiuz", "fsw", "count repeated all-repeated unique ignore-case zero-terminated skip-fields= "
             "skip-chars= check-chars= group"),
    "cut": ("nsz", "bcfd", "bytes= characters= fields= delimiter= complement only-delimited output-delimiter= "
            "zero-terminated"),
    "tr": ("cCdst", "", "complement delete squeeze-repeats truncate-set1"),
    "diff": ("aBbdEiNpqrsTtuwyZ#", "CDFIUWSxXL", "unified= context= recursive brief new-file ignore-all-space "
             "ignore-space-change ignore-blank-lines ignore-case side-by-side color= exclude= exclude-from= text "
             "strip-trailing-cr no-dereference suppress-common-lines label= report-identical-files minimal "
             "from-file= to-file= ignore-matching-lines= show-function-line= show-c-function width= expand-tabs "
             "initial-tab normal speed-large-files unidirectional-new-file horizon-lines= tabsize= palette="),
    "cmp": ("bls", "in", "print-bytes verbose quiet silent ignore-initial= bytes="),
    "comm": ("123iz", "", "check-order nocheck-order output-delimiter= total zero-terminated"),
    "jq": ("acCeEjMnrRsSt#", "fL", "arg== argjson== slurpfile== rawfile== args jsonargs tab indent= raw-output "
           "compact-output slurp null-input exit-status sort-keys raw-input join-output ascii-output color-output "
           "monochrome-output from-file= seq stream stream-errors raw-output0 unbuffered"),
    "yq": ("ePCMnrNj", "opI", "output-format= input-format= prettyPrint colors no-colors null-input exit-status "
           "unwrapScalar no-doc indent= raw-output"),
    "file": ("bikLhNr0E", "eFP", "brief mime mime-type mime-encoding keep-going dereference no-dereference no-pad raw "
             "print0 extension separator= exclude= parameter="),
    "stat": ("Lft", "c", "dereference file-system terse format= printf= cached="),
    "du": ("abcDhHklLmsSxP0", "dBtX", "all apparent-size bytes total dereference-args human-readable inodes "
           "dereference count-links max-depth= summarize separate-dirs si one-file-system exclude= exclude-from= "
           "threshold= time time-style= block-size= null"),
    "df": ("ahHiklPT", "Btx", "all block-size= human-readable si inodes local portability print-type type= "
           "exclude-type= output total"),
    "date": ("uRI", "dfr", "date= file= reference= utc universal rfc-email rfc-3339= iso-8601 debug"),
    "xxd": ("abCEeipudh", "cglsonR", ""),
    "hexdump": ("bcCdovx", "efns", ""),
    "od": ("bcdfilosvx", "AjNtwS", "address-radix= skip-bytes= read-bytes= format= output-duplicates width= strings= "
           "endian= traditional"),
    "cksum": ("z", "al", "algorithm= base64 check length= raw tag untagged zero"),
    "strings": ("adfwo#", "nte", "all data print-file-name bytes= radix= encoding= include-all-whitespace"),
    "rev": ("", "", ""), "fold": ("bs", "w", "bytes spaces width="), "tac": ("br", "s", "before regex separator="),
    "fmt": ("cstu#", "wpg", "crown-margin tagged-paragraph split-only uniform-spacing width= prefix= goal="),
    "expand": ("i#", "t", "initial tabs="), "unexpand": ("a#", "t", "all first-only tabs="),
    "paste": ("sz", "d", "delimiters= serial zero-terminated"),
    "join": ("iz", "aejotv12", "ignore-case check-order nocheck-order header zero-terminated"),
    "zcat": ("fqvltnN", "", "force quiet verbose list test"),
    "bat": ("pnAuP", "lHrm", "plain number show-all language= highlight-line= line-range= style= color= theme= "
            "decorations= tabs= wrap= terminal-width= list-languages list-themes diff file-name= map-syntax= "
            "squeeze-blank"),
    "hostname": ("fsiIdAa", "", "fqdn short ip-address all-ip-addresses domain all-fqdns alias"),
    "column": ("txJLe", "socNRHOWETrinpd", "table separator= output-separator= output-width= fillrows json "
               "keep-empty-lines table-columns= table-right= table-hide= table-name= table-order= table-wrap= "
               "table-noextreme= table-truncate="),
    "nl": ("p", "bdfhilnsvw", "body-numbering= section-delimiter= footer-numbering= header-numbering= "
           "line-increment= join-blank-lines= number-format= no-renumber number-separator= starting-line-number= "
           "number-width="),
    "bc": ("lqsw", "", "mathlib quiet standard warn"),
    "top": ("bcHiSs1", "ndpuUoOwE", ""),
    "pgrep": ("flaxnovciwA", "ruUGgPstFd", "full list-name list-full exact newest oldest inverse count ignore-case "
              "lightweight delimiter= pidfile="),
    "realpath": ("emLPqsz", "", "canonicalize-existing canonicalize-missing logical physical quiet strip no-symlinks "
                 "zero relative-to= relative-base="),
    "readlink": ("femnqsvz", "", "canonicalize canonicalize-existing canonicalize-missing no-newline quiet silent "
                 "verbose zero"),
}
OPTS.update({k: OPTS["grep"] for k in ("egrep", "fgrep")})
OPTS.update({k: ("bctwz", "l", "binary check tag text ignore-missing quiet status strict warn zero length=")
             for k in ("md5sum", "sha1sum", "sha256sum", "sha512sum", "b2sum")})
# Only print what they're given or facts about the machine, whatever their options.
ANY_ARGS = {"echo", "printf", "true", "false", "test", "[", ":", "expr", "pwd", "basename", "dirname", "which", "type",
            "sleep", "seq", "tput", "set", "unset", "export", "exit", "return", "wait", "ps", "lsof", "nproc",
            "uptime", "whoami", "locale", "cal", "id", "uname", "free", "lscpu", "{", "}", "do", "done", "then", "fi",
            "else", "elif", "if", "for", "while", "until", "in", "case", "esac"}
# Every option of these only changes what they print, so an argument the rules can't see ($X, $(…), a glob that
# could expand to "--something") can't make them run or write anything.
SUB_OK = {"grep", "egrep", "fgrep", "cat", "head", "tail", "wc", "ls", "stat", "du", "md5sum", "sha1sum", "sha256sum",
          "sha512sum", "b2sum", "cksum", "strings", "cut", "tr", "nl", "rev", "fold", "fmt", "expand", "unexpand",
          "paste", "tac", "comm", "cmp", "diff", "jq"}
# Test runners and checkers: they run the project's own code (the test-runner policy), but only with these options;
# the lists leave out plugins and configs from elsewhere (pytest -p/-c/--rootdir, eslint --plugin/--rulesdir),
# --basetemp (pytest empties it), installs (mypy --install-types) and remotes.
RUNNER_OPTS: dict[str, tuple[str, str, str]] = {
    "pytest": ("qvxslH", "kmnrW", "lf last-failed ff failed-first nf new-first sw stepwise stepwise-skip co "
               "collect-only tb= maxfail= durations= durations-min= no-header no-summary disable-warnings showlocals "
               "capture= verbose quiet exitfirst strict-markers runxfail cov= cov-report= cov-fail-under= cov-branch "
               "no-cov doctest-modules import-mode= color= code-highlight= timeout= deselect= ignore= ignore-glob= "
               "junitxml= setup-show fixtures markers version help log-level= log-cli-level= numprocesses= dist= "
               "maxprocesses= randomly-seed= continue-on-collection-errors full-trace"),
    "mypy": ("v", "pm", "strict ignore-missing-imports no-incremental show-error-codes pretty python-version= "
             "config-file= cache-dir= junit-xml= html-report= follow-imports= explicit-package-bases "
             "namespace-packages check-untyped-defs disallow-untyped-defs warn-unused-ignores no-error-summary "
             "exclude= show-column-numbers no-color-output warn-return-any disallow-any-generics package= module= "
             "verbose version"),
    "ruff": ("qne", "", "fix unsafe-fixes no-fix diff check select= ignore= extend-select= extend-ignore= "
             "output-format= statistics show-fixes no-cache quiet exit-zero exit-non-zero-on-fix line-length= "
             "target-version= preview no-preview show-files show-settings"),
    "black": ("qvS", "lt", "check diff quiet verbose line-length= target-version= skip-string-normalization "
              "skip-magic-trailing-comma preview fast safe color no-color include= exclude= extend-exclude= "
              "force-exclude="),
    "isort": ("cqv", "l", "check-only check diff profile= quiet verbose skip= skip-glob= line-length= "
              "float-to-top atomic"),
    "flake8": ("qv", "", "max-line-length= max-complexity= select= ignore= extend-ignore= extend-select= exclude= "
               "extend-exclude= count statistics show-source quiet verbose"),
    "pycodestyle": ("qv", "", "max-line-length= ignore= select= count statistics show-source quiet verbose"),
    "pyflakes": ("", "", ""), "tabnanny": ("qv", "", ""), "py_compile": ("q", "", ""),
    "pylint": ("E", "j", "errors-only disable= enable= jobs= score= reports= max-line-length= recursive="),
    "pyright": ("", "p", "outputjson level= pythonversion= verbose stats warnings project= skipunannotated"),
    "eslint": ("", "", "fix fix-dry-run ext= max-warnings= quiet cache cache-location= ignore-pattern= no-ignore "
               "report-unused-disable-directives color no-color no-error-on-unmatched-pattern"),
    "tsc": ("b", "p", "noEmit project= pretty strict incremental build listFiles outDir= declaration skipLibCheck "
            "target= module= version"),
    "prettier": ("cl", "", "check write list-different ignore-path= log-level= no-color cache"),
    "jest": ("io", "tw", "coverage ci runInBand silent verbose testNamePattern= bail passWithNoTests maxWorkers= "
             "testPathPattern= findRelatedTests onlyChanged json outputFile= watchAll="),
    "vitest": ("", "t", "run coverage reporter= silent bail= passWithNoTests"),
    "shellcheck": ("xaCV", "sfeSo", "shell= format= exclude= severity= external-sources color= enable="),
    "ctest": ("VQ", "jRE", "output-on-failure parallel= tests-regex= exclude-regex= test-dir= verbose quiet "
              "stop-on-failure rerun-failed"),
    "golangci-lint": ("v", "", "fix timeout= verbose fast new"),
    "biome": ("", "", "write apply verbose"),
    "tox": ("qvrp", "emf", "recreate parallel= skip-missing-interpreters= notest no-recreate-pkg"),
    "nox": ("rRl", "skt", "session= keywords= tags= reuse-existing-virtualenvs list no-error-on-missing-interpreters"),
    "unittest": ("vqfbc", "spkt", "locals buffer failfast catch"),
    "doctest": ("vf", "o", ""),
    "compileall": ("qflb", "rjxdi", ""),
}
RUNNER_OPTS["py.test"] = RUNNER_OPTS["pytest"]
GENERIC_RUNNER = ("qv", "", "quiet verbose version help")
# Build tools, after their verb.
BUILD_OPTS: dict[str, tuple[str, str, str]] = {
    "cargo": ("qvr", "pFj", "all workspace release package= lib bins bin= tests test= benches bench= examples "
              "example= all-targets features= all-features no-default-features quiet verbose no-fail-fast doc locked "
              "offline frozen jobs= target= target-dir= manifest-path= message-format= color= no-run check exclude= "
              "profile= keep-going no-deps document-private-items"),
    "go": ("", "", "v race cover short a n x json failfast benchmem trimpath run= count= timeout= tags= o= bench= "
           "p= mod= cpu= parallel= coverprofile= covermode= coverpkg= skip= shuffle= benchtime= list= m"),
    "meson": ("v", "Cj", "print-errorlogs suite= num-processes= reconfigure wipe buildtype= verbose"),
    "gradle": ("qi", "x", "offline info stacktrace no-daemon console= parallel quiet exclude-task= continue"),
    "mvn": ("qoBe", "T", "batch-mode offline quiet errors no-transfer-progress threads="),
    "dotnet": ("", "cvf", "configuration= verbosity= no-restore no-build framework= filter= nologo"),
    "swift": ("v", "cj", "configuration= filter= parallel jobs= verbose"),
    "zig": ("", "j", "summary= verbose"),
    "cmake": ("v", "SBGjt", "build= parallel= target= config= clean-first verbose"),
    "ninja": ("vn", "Cjk", ""),
}
PY_DANGER_RE = re.compile(r"\b(shutil\.rmtree|os\.(remove|unlink|rmdir|removedirs|system|popen|exec\w*|spawn\w*|kill)"
                          r"|subprocess|pty\.spawn|ctypes|socket\.|__import__\(['\"](os|subprocess)|send2trash"
                          r"|\.unlink\(|\.rmdir\(|eval\(|exec\()")
RUN_REMOTE_RE = re.compile(r"\b(curl|wget|fetch)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b|base64\s+(-d|--decode)[^|\n]*\|"
                           r"\s*(ba)?sh\b|\b(eval|exec)\s*\(\s*(requests|urllib|httpx|base64|atob|fetch)", re.I)
PY_NET_RE = re.compile(r"\b(requests|httpx|urllib|aiohttp|http\.client|ftplib|smtplib|paramiko)\b")


class Ctx:
    """Where a command runs: the folder (an absolute path), the current directory inside it, and its level; and your
    own rules (`judge_user.UserRules`), with what they allowed in this call."""

    def __init__(self, folder: dict[str, Any] | None, user: Any = None):
        self.root = posixpath.normpath((folder or {}).get("path") or "/nonexistent-folder")
        self.level = (folder or {}).get("level") or "read"
        self.cwd = self.root
        self.user = user or None
        self.user_allowed: list[str] = []    # your allow rules that covered a command
        self.rules_allowed = False           # a command the fixed rules allowed without one (with user rules only)

    def at_least(self, need: str) -> bool:
        return LEVELS.index(self.level) >= LEVELS.index(need) if self.level in LEVELS else False

    def resolve(self, word: str) -> str | None:
        """The absolute path a word names, or None when it can't be known (a variable, a substitution, ~user)."""
        if SUB in word or "$" in word or word.startswith("~") and not (word == "~" or word.startswith("~/")):
            return None
        if word == "~" or word.startswith("~/"):
            return "/home/~" + word[1:]                    # outside every folder, whatever $HOME is
        return posixpath.normpath(posixpath.join(self.cwd, word))

    def inside(self, path: str) -> bool:
        return path == self.root or path.startswith(self.root.rstrip("/") + "/")

    def rel(self, path: str) -> str:
        return posixpath.relpath(path, self.root)


def write_target(word: str, ctx: Ctx, what: str = "writes") -> Verdict:
    """A path a command writes to: inside the folder and not sensitive, at Edit or above."""
    if word in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "-") or word.isdigit():
        return allow("output to the terminal or nowhere", "write-null")
    path = ctx.resolve(word)
    if path is None:
        return ask(f"{what} to a path the rules can't know ({word.replace(SUB, '$(…)')})", "write-unknown")
    if not ctx.inside(path):
        return ask(f"{what} outside the folder ({word})", "write-outside")
    if SENSITIVE_WRITE_RE.search(ctx.rel(path)) or SECRET_FILE_RE.search(ctx.rel(path)):
        return ask(f"{what} to {ctx.rel(path)}, a dotfile or config that runs code or holds secrets", "write-dotfile")
    if not ctx.at_least("edit"):
        return ask(f"{what} a file in a folder at {ctx.level}", "write-level")
    return allow(f"{what} inside the folder", "write-inside")


def read_target(word: str, ctx: Ctx) -> Verdict | None:
    path = ctx.resolve(word)
    probe = path if path is not None else word
    if SECRET_FILE_RE.search(probe) or any(_glob_secret(part) for part in word.split("/")):
        return ask(f"reads {word}, which may hold credentials", "read-secret")
    return None


def _glob_secret(part: str) -> bool:
    """A glob that could match a secret's name (`.en?`, `.e*`, `id_*`). A glob starting with a wildcard doesn't match
    dotfiles, and one with fewer than two plain letters (`*`, `*.py`'s kin) is too wide to mean a secret."""
    if not re.search(r"[*?\[]", part):
        return False
    if part.startswith("."):
        return any(fnmatch.fnmatchcase(n, part) for n in DOT_SECRETS)
    return len(re.sub(r"[*?]|\[[^]]*]", "", part)) >= 2 and any(fnmatch.fnmatchcase(n, part) for n in NAMED_SECRETS)


def edit_rule(tool: str, args: dict[str, Any], ctx: Ctx) -> Verdict:
    paths = [args.get(k) for k in ("path", "from", "to", "source", "destination") if args.get(k)]
    found = []
    for p in paths:
        p = str(p)
        if p.startswith(("/", "~")) or ".." in p.split("/"):
            found.append(ask(f"{tool} names a path outside the folder ({p})", "write-outside"))
            continue
        found.append(write_target(p, ctx, "edits" if tool != "workspace_delete" else "deletes"))
    text = "\n".join(str(args.get(k) or "") for k in ("new", "content", "message"))
    if SECRET_RE.search(text):
        found.append(ask("the change contains what looks like a password, token or key", "credentials"))
    if RUN_REMOTE_RE.search(text):
        found.append(unsure("the change adds code that downloads and runs something", "edit-run-remote"))
    if tool == "workspace_delete":
        found.append(unsure("deletes a file (undo restores it)", "delete"))
    if not found:
        return ask(f"{tool} without a path", "empty")
    v = combine(found)
    return v if v.verdict != "allow" else allow("an edit inside an Edit folder (undo restores it)", "edit-inside")


def fetch_rule(args: dict[str, Any]) -> Verdict:
    url = str(args.get("url") or "")
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
    except ValueError:
        return ask(f"a URL that can't be read ({url[:80]})", "url")
    if u.scheme not in ("http", "https") or not host:
        return ask(f"fetches a {u.scheme or 'schemeless'} URL", "url")
    if u.username or u.password or SECRET_RE.search(url) or any(
            re.search(r"(token|key|secret|password|passwd|auth|session|sig)", k, re.I) for k, _ in parse_qsl(u.query)):
        return ask("the URL carries credentials", "credentials")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if not ip.is_global:
            return ask(f"fetches a private address ({host})", "private")
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".internal", ".lan", ".localhost", ".home.arpa")):
            return ask(f"fetches a local name ({host})", "private")
    segments = [s for s in u.path.split("/") if s]
    if len(url) > 2000 or any(len(v) >= 64 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", v) for _, v in parse_qsl(u.query)) \
            or any(ENCODED_RE.fullmatch(s) and not SLUG_RE.fullmatch(s) and not SHA_RE.fullmatch(s) for s in segments):
        return ask("the URL carries a long encoded value (it could send data out)", "exfil-url")
    if len(u.path) > MAX_DOCS_PATH or any(ENCODED_RE.fullmatch(s) for s in segments):
        return unsure(f"fetches {host} with a long path", "fetch")
    if not u.query and host in DOCS_HOSTS:
        return allow(f"reads documentation on {host}", "docs")
    return unsure(f"fetches {host}", "fetch")


def gpu_rule(tool: str, est: dict[str, Any]) -> Verdict:
    secs = float(est.get("seconds") or 0)
    gb = float(est.get("memory_gb") or 0)
    share = float(est.get("memory_share") or 0)
    if secs > HUGE_JOB_S or gb > HUGE_JOB_GB:
        return ask(f"{tool} would run about {secs / 60:.0f} min or need {gb:.0f} GB", "huge-job")
    if secs <= LONG_JOB_S and share <= LONG_JOB_SHARE:
        return allow(f"{tool} is a short GPU job (about {secs:.0f} s)", "short-job")
    return unsure(f"{tool} is a long GPU job (about {secs / 60:.0f} min, {gb:.0f} GB)", "long-job")


TITLE_TOOLS = ("calendar_add", "calendar_update")
TITLE_STOP = {"the", "and", "with", "for", "from", "about", "into", "onto", "our", "your", "his", "her", "their", "its"}


def _stem(w: str) -> str:
    w = w.lower().replace("’", "'").strip("'")
    for suf in ("'s", "s'", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def title_rule(call: dict[str, Any], said: list[str]) -> Verdict | None:
    """calendar 4.5: a calendar item's title must be in the user's own words. A title with a word they didn't say (a
    person they didn't name, an event their task didn't ask for) asks; otherwise the model decides. None: not this
    rule's call."""
    args = call.get("args") or call.get("arguments") or {}
    if call.get("tool") not in TITLE_TOOLS or not isinstance(args.get("title"), str) or not args["title"].strip():
        return None
    heard = {_stem(w) for m in said for w in re.findall(r"[\w'’]+", str(m))}
    words = [w.strip("'’") for w in re.findall(r"[\w'’]+", args["title"])]
    new = [w for w in words if len(w) >= 3 and w.lower() not in TITLE_STOP and _stem(w) not in heard]
    if new:
        return ask(f"the title has words you didn't say ({', '.join(new[:4])})", "title-words")
    return None


def classify(call: dict[str, Any], folder: dict[str, Any] | None = None, user: Any = None) -> Verdict:
    """The rules' verdict on one tool call (see the module docstring). `user`: your command rules
    (`judge_user.UserRules`), applied to each command of a `workspace_run`."""
    tool = str(call.get("tool") or "")
    args = call.get("args") or call.get("arguments") or {}
    ctx = Ctx(folder, user)
    from .judge_commands import classify_command     # it imports this module's helpers
    from .judge_user import line_verdict

    if tool in ("workspace_run", "workspace_shell"):
        if (args.get("where") or "sandbox") != "sandbox":
            return ask("runs on your machine, outside the sandbox: always asks", "host")
        if not ctx.at_least("run"):
            return ask(f"commands need Run; the folder is at {ctx.level}", "run-level")
        v = classify_command(str(args.get("command") or ""), ctx)
        if v.verdict == "allow" and args.get("network") and (ctx.rules_allowed or not ctx.user_allowed):
            # with the internet on, even a reading command could send what it reads: no rule allows; the model decides
            # (your own allow rules do, when they cover every command in the line)
            return unsure(f"{v.reason}, with the internet on", "network")
        return line_verdict(v, ctx, bool(args.get("network"))) if v.verdict == "allow" and ctx.user_allowed else v
    if tool == "workspace_python":
        code = str(args.get("code") or "")
        if SECRET_RE.search(code):
            return ask("the code contains what looks like a password, token or key", "credentials")
        if m := PY_DANGER_RE.search(code):
            return ask(f"the code deletes files or runs commands ({m.group(0)})", "python-danger")
        if PY_NET_RE.search(code):
            return unsure("the code uses the network", "python-net")
        return unsure("runs Python in the sandbox", "python")
    if tool == "workspace_git_commit":
        return ask("commits ask every time (plan 27.3)", "git-commit")
    if tool in ("workspace_edit", "workspace_write", "workspace_move", "workspace_delete"):
        if not ctx.at_least("edit"):
            return ask(f"edits need Edit; the folder is at {ctx.level}", "write-level")
        return edit_rule(tool, args, ctx)
    if tool in ("web_fetch",):
        return fetch_rule(args)
    if tool in ("web_search", "workspace_folders", "workspace_tree", "workspace_read", "workspace_search",
                "workspace_git"):
        return allow("only reads", "read-tool")
    if call.get("estimate"):
        return gpu_rule(tool, call["estimate"])
    return unsure(f"{tool or 'this tool'} isn't one the rules know", "unknown-tool")
