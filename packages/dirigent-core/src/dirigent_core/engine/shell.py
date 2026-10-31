"""Reading a shell command far enough to place a reference in it.

This is no shell parser. It follows what decides how a reference has to be written and what it
may hold: quotes, comments, here-documents, substitutions, parameter expansions, and the places
bash evaluates a value as an arithmetic expression. What it cannot follow to the end, it reports
as unread rather than guessing, and a command with a reference in it is then refused.
"""

import re
from collections.abc import Collection
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, Field

#: A reference's place in the text a reader is handed, so its offset is one character wide.
REFERENCE_MARK: Final = "\0"

#: How a refusal names a reference a reader passed over without placing.
REFERENCE_OPENER: Final = "${"

#: Frames a command is read in, where a word can begin and a comment can start.
_TOP: Final = "top"
_SUBSHELL: Final = "subshell"
_BACKTICK: Final = "backtick"
_COMMAND_FRAMES: Final = frozenset({_TOP, _SUBSHELL, _BACKTICK})

_SINGLE: Final = "single"
_ANSI: Final = "ansi"
_DOUBLE: Final = "double"
_ARITHMETIC: Final = "arithmetic"
_BRACKET: Final = "bracket"
_GROUP: Final = "group"
_SUBSCRIPT: Final = "subscript"
_BRACE: Final = "brace"
_TEST: Final = "test"
_HERE: Final = "here"

#: Frames that hold an expression, where a ``(`` groups and a ``[`` opens a subscript.
_EXPRESSION_FRAMES: Final = frozenset({_ARITHMETIC, _BRACKET, _GROUP, _SUBSCRIPT})

#: Words that leave the next word in command position.
_KEYWORDS: Final = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "while",
        "until",
        "do",
        "done",
        "!",
        "time",
        "{",
        "}",
        "command",
        "builtin",
        "coproc",
    }
)

#: Words that take options and then a command, as ``time -p`` and ``command -p`` do.
_PREFIXES: Final = frozenset({"time", "command", "builtin"})

#: Commands whose words name a variable, and take the attribute flags.
_DECLARERS: Final = frozenset({"declare", "typeset", "local", "readonly", "export"})

#: Commands that evaluate every word they are given as an expression or a subscript.
_EVALUATORS: Final = frozenset({"let", "unset"})

#: The ``[[ ]]`` operators whose operands are evaluated: the numeric ones, and ``-v``'s subscript.
_EVALUATING_TESTS: Final = frozenset({"-eq", "-ne", "-lt", "-le", "-gt", "-ge", "-v"})

_ASSIGNMENT: Final = re.compile(r"[A-Za-z_]\w*(\[.*\])?\+?=")
_NAME: Final = re.compile(r"[A-Za-z_]\w*")
_FUNCTION_PARENS: Final = re.compile(r"\(\s*\)")
_DESCRIPTOR: Final = re.compile(r"[0-9]+|\{[A-Za-z_]\w*\}")
_BRACE_NAME: Final = re.compile(r"[#!]?(?:[A-Za-z_]\w*|[0-9]+|[@*#?$!-])")

#: What ends a here-document's delimiter when it is not quoted.
_WORD_END: Final = " \t\n;&|()<>"

#: What ends a command for a reading that follows no quote.
_COMMAND_BOUNDARY: Final = re.compile(r"[;|\n(`]|(?<![<>])&")
_REDIRECTION: Final = re.compile(r"(?:[0-9]*|\{[A-Za-z_]\w*\})[<>]")
_BARE_REDIRECTION: Final = re.compile(r"[0-9]*[<>]+&?")
_WORD_START: Final = r"(?<![^\s;&|(){}!\"'`])"
_TEST_OPENER: Final = re.compile(rf"{_WORD_START}\[\[\s")
_TEST_CLOSER: Final = re.compile(r"(?<!\\)\]\](?=[\s;&|)]|$)")
_TEST_CLAUSE_END: Final = re.compile(r"&&|\|\||(?<!\\)\]\](?=[\s;&|)]|$)")
_EVALUATING_OPERATOR: Final = re.compile(rf"{_WORD_START}(?:-eq|-ne|-lt|-le|-gt|-ge|-v)(?![^\s)\"'])")
_ATTRIBUTE_DECLARERS: Final = frozenset({"declare", "typeset", "local"})
_QUOTED_COMPOUND: Final = re.compile(rf"{_WORD_START}(?:declare|typeset|local)\s[^\n;&|]*[\"']\w+\+?=\([^\n)]*$")
_COMPOUND_OPENER: Final = "=("


class Quoting(StrEnum):
    """What surrounds a reference, which decides how it is written so it stays one word."""

    BARE = "bare"
    DOUBLE = "double"
    LITERAL = "literal"
    HERE_DOCUMENT = "here_document"


class Placed(BaseModel):
    """Where one reference landed."""

    quoting: Quoting
    integer: bool = False
    """Whether bash evaluates the value here, so that only an integer is safe."""


class Unread(BaseModel):
    """The construct a command could not be followed past."""

    opener: str
    line: int


class ShellReading(BaseModel):
    """What a reader made of a command: each reference by its offset, and where it stopped."""

    places: dict[int, Placed] = Field(default_factory=dict[int, Placed])
    unread: Unread | None = None


class _Frame(BaseModel):
    """One thing the shell has open and not yet closed."""

    kind: str
    opener: str = ""
    opened_at: int = 0
    arithmetic: bool = False
    word: str = ""
    in_word: bool = False
    expect_command: bool = True
    command: str = ""
    associative: bool = False
    case_depth: int = 0
    clause: list[int] = Field(default_factory=list[int])
    clause_evaluates: bool = False
    name_ended: bool = False
    delimiter: str = ""
    strip_tabs: bool = False
    quoted: bool = False
    at_line_start: bool = False
    redirected: bool = False
    prefixed: bool = False


class _HereDocument(BaseModel):
    """A here-document named on a line, whose body starts at the next newline."""

    delimiter: str
    strip_tabs: bool
    quoted: bool
    opened_at: int


class _Reader:
    """A single pass over a command, one character or construct per step."""

    def __init__(self, text: str, references: Collection[int]) -> None:
        """Start at the top of the command with nothing open."""
        self.text = text
        self.references = frozenset(references)
        self.index = 0
        self.stack = [_Frame(kind=_TOP)]
        self.pending: list[_HereDocument] = []
        self.associative: set[str] = set()
        self.declares_integer = False
        self.places: dict[int, Placed] = {}
        self.unread: Unread | None = None

    def read(self) -> ShellReading:
        """Read to the end and report what was found."""
        while self.index < len(self.text):
            self._step()
        self._end_word(self.stack[-1])
        if len(self.stack) > 1:
            self._stop_at(self.stack[-1].opener, self.stack[-1].opened_at)
        for offset in sorted(self.references - self.places.keys()):
            self.places[offset] = Placed(quoting=Quoting.BARE)
            self._stop_at(REFERENCE_OPENER, offset)
        if self.declares_integer:
            for place in self.places.values():
                place.integer = True
        return ShellReading(places=self.places, unread=self.unread)

    def _step(self) -> None:
        top = self.stack[-1]
        if top.kind == _HERE and top.at_line_start:
            self._here_line(top)
        elif self.index in self.references:
            self._place()
            self.index += 1
        elif top.kind == _SINGLE:
            self._single()
        elif top.kind == _ANSI:
            self._ansi(top)
        elif top.kind == _DOUBLE:
            self._double()
        elif top.kind == _HERE:
            self._here_body(top)
        elif top.kind == _BRACE:
            self._brace(top)
        elif top.kind == _TEST:
            self._test(top)
        elif top.kind in _EXPRESSION_FRAMES:
            self._expression(top)
        else:
            self._command(top)

    def _push(self, kind: str, opener: str, width: int, **fields: object) -> _Frame:
        frame = _Frame.model_validate({"kind": kind, "opener": opener, "opened_at": self.index, **fields})
        self.stack.append(frame)
        self.index += width
        return frame

    def _stop_at(self, opener: str, offset: int) -> None:
        if self.unread is None:
            self.unread = Unread(opener=opener, line=self.text.count("\n", 0, offset) + 1)

    def _word_frame(self) -> _Frame | None:
        """The command or test whose word the current character belongs to, through its quotes."""
        for frame in reversed(self.stack):
            if frame.kind in _COMMAND_FRAMES or frame.kind == _TEST:
                return frame
            if frame.kind not in (_SINGLE, _ANSI, _DOUBLE):
                return None
        return None

    def _note(self, character: str) -> None:
        frame = self._word_frame()
        if frame is not None:
            frame.word += character
            frame.in_word = True

    def _place(self) -> None:
        """Record where the reference at this offset sits, and whether its value is evaluated."""
        offset = self.index
        evaluated = any(frame.arithmetic for frame in self.stack) or self._names_a_variable()
        self.places[offset] = Placed(quoting=self._quoting(), integer=evaluated)
        for frame in reversed(self.stack):
            if frame.kind == _TEST:
                frame.clause.append(offset)
                break
        self._note(REFERENCE_MARK)

    def _names_a_variable(self) -> bool:
        frame = self._word_frame()
        return frame is not None and frame.command in _DECLARERS and "=" not in frame.word

    def _quoting(self) -> Quoting:
        for frame in reversed(self.stack):
            if frame.kind in (_SINGLE, _ANSI):
                return Quoting.LITERAL
            if frame.kind == _DOUBLE:
                return Quoting.DOUBLE
            if frame.kind == _HERE:
                return Quoting.LITERAL if frame.quoted else Quoting.HERE_DOCUMENT
            if frame.kind in _COMMAND_FRAMES:
                return Quoting.BARE
        return Quoting.BARE

    def _single(self) -> None:
        character = self.text[self.index]
        self.index += 1
        if character == "'":
            self.stack.pop()
        else:
            self._note(character)

    def _ansi(self, top: _Frame) -> None:
        character = self.text[self.index]
        if character == "\\":
            # dash reads ``$'a\'`` as closed where bash reads it as open, so neither can be assumed.
            if self.text[self.index + 1 : self.index + 2] == "'":
                self._stop_at(top.opener, top.opened_at)
            self._escape()
            return
        self.index += 1
        if character == "'":
            self.stack.pop()

    def _escape(self) -> None:
        """Pass over a backslash and what it escapes, which is never a reference.

        A backslash before a bare reference escapes the quote it is written with and leaves the
        value open, so a reader stops there.
        """
        if self.index + 1 in self.references:
            if self._quoting() is Quoting.BARE:
                self._stop_at("\\", self.index)
            self.index += 1
        else:
            self.index += 2

    def _double(self) -> None:
        character = self.text[self.index]
        if character == "\\":
            self._escape()
        elif character == '"':
            self.stack.pop()
            self.index += 1
        elif not self._substitution(character):
            self._note(character)
            self.index += 1

    def _substitution(self, character: str) -> bool:
        """Open what ``$`` or a backquote opens here, and say whether anything was consumed."""
        if character == "`":
            if self.stack[-1].kind == _BACKTICK:
                self.stack.pop()
                self.index += 1
            else:
                self._note(REFERENCE_MARK)
                self._push(_BACKTICK, "`", 1)
            return True
        if character != "$":
            return False
        ahead = self.text[self.index + 1 : self.index + 3]
        self._note(REFERENCE_MARK)
        if ahead[:1] == "$":
            self.index += 2
        elif ahead == "((":
            self._push(_ARITHMETIC, "$((", 3, arithmetic=True)
        elif ahead[:1] == "(":
            self._push(_SUBSHELL, "$(", 2)
        elif ahead[:1] == "[":
            self._push(_BRACKET, "$[", 2, arithmetic=True)
        elif ahead[:1] == "{":
            self._open_brace()
        else:
            self.index += 1
        return True

    def _open_brace(self) -> None:
        """Open ``${``, reading its name, so what follows the name can say it holds an expression."""
        frame = self._push(_BRACE, "${", 2)
        name = _BRACE_NAME.match(self.text, self.index)
        if name is None:
            return
        self.index = name.end()
        frame.name_ended = True
        if self.text[self.index : self.index + 1] != "[":
            return
        if self.text[self.index + 1 : self.index + 3] in ("@]", "*]"):
            self.index += 3
            return
        evaluated = name.group().lstrip("#!") not in self.associative
        self._push(_SUBSCRIPT, "[", 1, arithmetic=evaluated)

    def _brace(self, top: _Frame) -> None:
        character = self.text[self.index]
        if top.name_ended:
            top.name_ended = False
            if character == ":" and self.text[self.index + 1 : self.index + 2] not in ("-", "=", "?", "+"):
                top.arithmetic = True
        if character == "\\":
            self._escape()
        elif character == "}":
            self.stack.pop()
            self.index += 1
        elif not self._quote(character) and not self._substitution(character):
            self.index += 1

    def _quote(self, character: str) -> bool:
        """Open a quote here, where one is read at all, and say whether one was opened."""
        if character == '"':
            self._push(_DOUBLE, '"', 1)
            return True
        if character == "'" and not self._inside_double():
            self._push(_SINGLE, "'", 1)
            return True
        return False

    def _inside_double(self) -> bool:
        for frame in reversed(self.stack):
            if frame.kind == _DOUBLE:
                return True
            if frame.kind != _BRACE and frame.kind != _SUBSCRIPT:
                return False
        return False

    def _expression(self, top: _Frame) -> None:
        character = self.text[self.index]
        ahead = self.text[self.index + 1 : self.index + 2]
        if character == "\\":
            self._escape()
        elif character == "(":
            self._push(_GROUP, "(", 1, arithmetic=True)
        elif character == "[":
            self._push(_SUBSCRIPT, "[", 1, arithmetic=True)
        elif character == ")" and top.kind == _ARITHMETIC:
            # A ``)`` that closes a ``((`` alone means a shell reads two subshells.
            self.stack.pop()
            self.index += 2 if ahead == ")" else 1
        elif character == ")" and top.kind == _GROUP:
            self.stack.pop()
            self.index += 1
        elif character == "]" and top.kind in (_BRACKET, _SUBSCRIPT):
            self.stack.pop()
            self._note(character)
            self.index += 1
        elif not self._quote(character) and not self._substitution(character):
            self.index += 1

    def _command(self, top: _Frame) -> None:
        character = self.text[self.index]
        ahead = self.text[self.index + 1 : self.index + 2]
        if character in " \t":
            self._end_word(top)
            self.index += 1
        elif character == "\n":
            self._end_word(top)
            self._reset_command(top)
            self.index += 1
            self._start_here_document()
        elif character == "\\":
            if ahead != "\n" and self.index + 1 not in self.references:
                self._note(ahead)
            self._escape()
        elif character == "#" and not top.in_word:
            self._comment(top)
        elif character in ";|":
            self._end_word(top)
            self._reset_command(top)
            self.index += 1
        elif character == "&":
            if self.text[self.index - 1 : self.index] not in ("<", ">"):
                self._end_word(top)
                self._reset_command(top)
            self.index += 1
        elif character in "<>":
            if _DESCRIPTOR.fullmatch(top.word) is not None:
                top.word = ""
                top.in_word = False
            self._end_word(top)
            self._redirection(top)
        elif character == "(":
            self._end_word(top)
            top.redirected = False
            parens = _FUNCTION_PARENS.match(self.text, self.index)
            if parens is not None:
                self._reset_command(top)
                self.index = parens.end()
            elif ahead == "(":
                self._push(_ARITHMETIC, "((", 2, arithmetic=True)
            else:
                self._push(_SUBSHELL, "(", 1)
        elif character == ")":
            self._end_word(top)
            if top.kind == _SUBSHELL and top.case_depth == 0:
                self.stack.pop()
                if top.opener == "(":
                    self._reset_command(self.stack[-1])
            else:
                self._reset_command(top)
            self.index += 1
        elif character == "[" and self._opens_test(top):
            top.expect_command = False
            top.command = "[["
            self._push(_TEST, "[[", 2)
        elif character == "[" and self._subscript_is_evaluated(top):
            self._note(character)
            self._push(_SUBSCRIPT, "[", 1, arithmetic=True)
        elif character == "$" and ahead == "'":
            self._note(REFERENCE_MARK)
            self._push(_ANSI, "$'", 2)
        elif self._quote(character):
            top.in_word = True
        elif not self._substitution(character):
            self._note(character)
            self.index += 1

    def _opens_test(self, top: _Frame) -> bool:
        ahead = self.text[self.index + 1 : self.index + 3]
        return top.expect_command and not top.in_word and ahead[:1] == "[" and ahead[1:] in (" ", "\t", "\n")

    def _subscript_is_evaluated(self, top: _Frame) -> bool:
        """Whether a ``[`` opens an indexed array's subscript that an assignment evaluates.

        ``echo a[1]`` is a glob and ``a[1]=x`` is an assignment, which only the end says.
        """
        if _NAME.fullmatch(top.word) is None or top.word in self.associative:
            return False
        depth = 0
        for index in range(self.index, len(self.text)):
            character = self.text[index]
            if character == "\n":
                return False
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth == 0:
                    return self.text[index + 1 : index + 2] == "=" or self.text[index + 1 : index + 3] == "+="
        return False

    def _comment(self, top: _Frame) -> None:
        """Pass over a comment, which runs to the newline, or to the backquote that ends its command."""
        end = self.index
        while end < len(self.text) and self.text[end] != "\n" and not (top.kind == _BACKTICK and self.text[end] == "`"):
            if end in self.references:
                self.places[end] = Placed(quoting=Quoting.LITERAL)
            end += 1
        self.index = end

    def _redirection(self, top: _Frame) -> None:
        """Pass over a redirection operator, whose next word is a target and no command."""
        if self.text.startswith("<<<", self.index):
            top.redirected = True
            self.index += 3
        elif self.text.startswith("<<", self.index):
            self._here_document()
        else:
            top.redirected = True
            self.index += 1

    def _here_document(self) -> None:
        """Read a here-document's delimiter, whose body starts at the next newline."""
        opened_at = self.index
        index = self.index + 2
        strip_tabs = self.text[index : index + 1] == "-"
        index += 1 if strip_tabs else 0
        while self.text[index : index + 1] in (" ", "\t"):
            index += 1
        delimiter = ""
        quoted = False
        while index < len(self.text) and self.text[index] not in _WORD_END:
            character = self.text[index]
            if character == "\\":
                quoted = True
                delimiter += self.text[index + 1 : index + 2]
                index += 2
            elif character in "'\"":
                quoted = True
                close = self.text.find(character, index + 1)
                if close < 0:
                    self._stop_at(character, index)
                    close = len(self.text)
                delimiter += self.text[index + 1 : close]
                index = close + 1
            else:
                delimiter += character
                index += 1
        for offset in range(opened_at, min(index, len(self.text))):
            if offset in self.references:
                self.places[offset] = Placed(quoting=Quoting.LITERAL)
                self._stop_at("<<", opened_at)
        self.index = index
        if delimiter:
            self.pending.append(
                _HereDocument(delimiter=delimiter, strip_tabs=strip_tabs, quoted=quoted, opened_at=opened_at)
            )

    def _start_here_document(self) -> None:
        if self.pending:
            here = self.pending.pop(0)
            self.stack.append(
                _Frame(
                    kind=_HERE,
                    opener=f"<<{here.delimiter}",
                    opened_at=here.opened_at,
                    delimiter=here.delimiter,
                    strip_tabs=here.strip_tabs,
                    quoted=here.quoted,
                    at_line_start=True,
                )
            )

    def _here_line(self, top: _Frame) -> None:
        """Look at a line of a here-document's body as a whole: it may be the delimiter."""
        end = self.text.find("\n", self.index)
        end = len(self.text) if end < 0 else end
        line = self.text[self.index : end]
        written = line.lstrip("\t") if top.strip_tabs else line
        if written == top.delimiter or (written == f"{top.delimiter}`" and self._inside_backtick()):
            self.stack.pop()
            self.index = end + 1 if written == top.delimiter else end - 1
            self._start_here_document()
            return
        top.at_line_start = False
        if top.quoted:
            for offset in range(self.index, end):
                if offset in self.references:
                    self.places[offset] = Placed(quoting=Quoting.LITERAL)
            self.index = end + 1
            top.at_line_start = True

    def _inside_backtick(self) -> bool:
        return any(frame.kind == _BACKTICK for frame in self.stack)

    def _here_body(self, top: _Frame) -> None:
        character = self.text[self.index]
        if character == "\\":
            self._escape()
        elif character == "\n":
            top.at_line_start = True
            self.index += 1
        elif not self._substitution(character):
            self.index += 1

    def _test(self, top: _Frame) -> None:
        character = self.text[self.index]
        two = self.text[self.index : self.index + 2]
        if character in " \t\n;":
            popped = self._end_test_word(top)
            self.index += 0 if popped else 1
        elif character == "\\":
            if self.index + 1 not in self.references:
                self._note(self.text[self.index + 1 : self.index + 2])
            top.quoted = True
            self._escape()
        elif two in ("&&", "||") or character in "()":
            if not self._end_test_word(top):
                self._end_clause(top)
                self.index += 2 if two in ("&&", "||") else 1
        elif self._quote(character):
            top.in_word = True
            top.quoted = True
        elif not self._substitution(character):
            self._note(character)
            self.index += 1

    def _end_test_word(self, top: _Frame) -> bool:
        """Finish a word of a ``[[ ]]``, and say whether it was the ``]]`` that closes it."""
        word = top.word
        quoted = top.quoted
        top.word = ""
        top.in_word = False
        top.quoted = False
        if word in _EVALUATING_TESTS:
            top.clause_evaluates = True
        if word == "]]" and not quoted:
            self._end_clause(top)
            self.stack.pop()
            return True
        return False

    def _end_clause(self, top: _Frame) -> None:
        if top.clause_evaluates:
            for offset in top.clause:
                self.places[offset].integer = True
        top.clause = []
        top.clause_evaluates = False

    def _end_word(self, frame: _Frame) -> None:
        """Finish a word of a command, which is what tells a command from its arguments."""
        if frame.kind == _TEST:
            self._end_test_word(frame)
            return
        if frame.kind not in _COMMAND_FRAMES or not frame.in_word:
            return
        word = frame.word
        frame.word = ""
        frame.in_word = False
        if frame.redirected:
            frame.redirected = False
        elif word in ("{", "}"):
            self._reset_command(frame)
        elif frame.expect_command:
            self._command_word(frame, word)
        elif frame.command in _DECLARERS:
            self._declared_word(frame, word)

    def _command_word(self, frame: _Frame, word: str) -> None:
        if word == "esac":
            frame.case_depth = max(0, frame.case_depth - 1)
        elif word == "case":
            frame.case_depth += 1
            frame.expect_command = False
            frame.command = word
        elif word in _KEYWORDS:
            frame.prefixed = word in _PREFIXES
        elif not (frame.prefixed and word.startswith("-")) and _ASSIGNMENT.match(word) is None:
            frame.expect_command = False
            frame.command = word
            frame.arithmetic = word in _EVALUATORS

    def _declared_word(self, frame: _Frame, word: str) -> None:
        if word.startswith("-"):
            self.declares_integer = self.declares_integer or "i" in word
            frame.associative = frame.associative or "A" in word
        elif frame.associative:
            name = _NAME.match(word)
            if name is not None:
                self.associative.add(name.group())

    def _reset_command(self, frame: _Frame) -> None:
        frame.expect_command = True
        frame.command = ""
        frame.arithmetic = False
        frame.associative = False
        frame.prefixed = False


def read_shell(text: str, references: Collection[int]) -> ShellReading:
    """Read a command in which each offset of ``references`` holds a reference, one character wide."""
    return _Reader(text, references).read()


def evaluated_in_any_quoting(text: str, offset: int) -> bool:
    """Whether bash may evaluate the value of the reference at this offset, whatever the text quotes.

    It reads neither quotes, comments nor here-documents, so none can hide a word from it, and a
    word in a string can read as one. It looks at the word in command position of the text since
    the last separator, so ``echo let ${x}`` and ``echo "let me ${x}"`` take any value.
    """
    before = text[:offset]
    words = _command_words(_COMMAND_BOUNDARY.split(before)[-1])
    if words and not before[-1].isspace():
        words.pop()
    command = _unquoted(words[0]) if words else ""
    named = bool(words) and _unquoted(words[-1]) == "-v"
    return (
        command in _EVALUATORS
        or (named and command in ("[", "[[", "test", "printf"))
        or (command == "read" and "<" not in before[before.rfind(words[0]) :])
        or _in_evaluating_test(text, offset)
        or _in_compound_subscript(before)
        or _QUOTED_COMPOUND.search(before) is not None
        or _declares_attribute(text)
    )


def _command_words(segment: str) -> list[str]:
    """A command's words from the one in command position on, with no regard to quotes."""
    words = segment.split()
    index = 0
    while index < len(words):
        word = _unquoted(words[index])
        if word == "case":
            index += 1
            while index < len(words) and not words[index].endswith(")"):
                index += 1
            index += 1
        elif word == "function" or _BARE_REDIRECTION.fullmatch(word) is not None:
            index += 2
        elif word in _PREFIXES:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
        elif (
            word in _KEYWORDS
            or word.endswith(")")
            or _REDIRECTION.match(word) is not None
            or _ASSIGNMENT.match(word) is not None
        ):
            index += 1
        else:
            return words[index:]
    return []


def _unquoted(word: str) -> str:
    return word.strip("\"'\\")


def _in_evaluating_test(text: str, offset: int) -> bool:
    """Whether this offset is in a clause of a ``[[ ]]`` that has an evaluating operator."""
    opener = None
    for found in _TEST_OPENER.finditer(text, 0, offset):
        ahead = _command_words(_COMMAND_BOUNDARY.split(text[: found.start()])[-1])
        if not ahead:
            opener = found
    if opener is None or _TEST_CLOSER.search(text, opener.end(), offset) is not None:
        return False
    start = opener.end()
    for separator in _TEST_CLAUSE_END.finditer(text, start, offset):
        start = separator.end()
    end = _TEST_CLAUSE_END.search(text, offset + 1)
    return _EVALUATING_OPERATOR.search(text, start, end.start() if end else len(text)) is not None


def _in_compound_subscript(before: str) -> bool:
    """Whether the end of this text is inside a ``[`` of a compound assignment, ``a=([x]=1)``."""
    opener = before.rfind(_COMPOUND_OPENER)
    if opener < 0:
        return False
    depth = 0
    inner = before[opener + len(_COMPOUND_OPENER) :]
    for character in inner:
        depth += (character == "(") - (character == ")")
        if depth < 0:
            return False
    return inner.rfind("[") > inner.rfind("]")


def _declares_attribute(text: str) -> bool:
    """Whether any command here gives a variable the integer or nameref attribute."""
    for segment in _COMMAND_BOUNDARY.split(text):
        words = _command_words(segment)
        if words and _unquoted(words[0]) in _ATTRIBUTE_DECLARERS:
            for word in words[1:]:
                if word.startswith("-") and ("i" in word or "n" in word):
                    return True
    return False
