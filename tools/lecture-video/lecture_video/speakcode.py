"""Code in the narration, written as on the slide in backticks, turned into words.

    The loop runs while `count < 5`, and `count++` adds one.

Inside a code span, every token without spaces (`count++`, `Integer.MAX_VALUE`, `VisitorCount.in`)
is spoken in English: names are split into words (nextDouble -> next double, MAX_VALUE -> max value)
and the symbols in it are said in English. Operators between spaces (`count < 5`), numbers and
one-letter names (`i`) are spoken in the language of the narration. runs() returns the pieces with their language, so a German
voice can say the English pieces with English pronunciation (tts.Voice).
"""
from __future__ import annotations

import re

CODE = re.compile(r"`([^`]+)`")

# operators between spaces, in the narration's language
OPERATORS = {
    "en": {"<=": "less than or equal to", ">=": "greater than or equal to", "==": "equals equals",
           "!=": "not equals", "&&": "and", "||": "or", "+=": "plus equals", "-=": "minus equals",
           "*=": "times equals", "/=": "divided by equals", "<": "less than", ">": "greater than",
           "=": "equals", "+": "plus", "-": "minus", "*": "times", "/": "divided by", "%": "modulo",
           "?": "question mark", ":": "colon"},
    "de": {"<=": "kleiner gleich", ">=": "größer gleich", "==": "gleich gleich", "!=": "ungleich",
           "&&": "und", "||": "oder", "+=": "plus gleich", "-=": "minus gleich", "*=": "mal gleich",
           "/=": "durch gleich", "<": "kleiner", ">": "größer", "=": "gleich", "+": "plus", "-": "minus",
           "*": "mal", "/": "durch", "%": "modulo", "?": "Fragezeichen", ":": "Doppelpunkt"},
}

# symbols inside a token, always English (the token is spoken in English)
SYMBOLS = [("++", " plus plus "), ("--", " minus minus "), ("()", " "), ("[]", " array "),
           ("<=", " less than or equal to "), (">=", " greater than or equal to "), ("==", " equals equals "),
           ("!=", " not equals "), ("&&", " and "), ("||", " or "), ("::", " "), (".", " dot "), ("_", " "),
           ("<", " of "), (">", " "), ("!", " not "), ("(", " "), (")", " "), ("[", " "), ("]", " "),
           ("{", " "), ("}", " "), (";", " "), (",", " "), ("\"", " "), ("'", " "), ("#", " hash "),
           ("%", " percent "), ("=", " equals "), ("+", " plus "), ("*", " times "), ("/", " slash "),
           ("\\", " backslash "), ("@", " at "), ("$", " dollar ")]

NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?[fFdDlL]?$")


def split_name(word: str) -> str:
    """nextDouble -> next Double, VisitorCount -> Visitor Count, ROOT -> root, HTMLPage -> HTML Page"""
    if word.isupper() and word.isalpha():
        # up to 3 capitals is an acronym the voice spells (DIN, URL, JDK); longer is a word (ROOT, VALUE)
        return word if len(word) <= 3 else word.lower()
    word = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word)
    word = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", word)
    return word


def token_words(token: str) -> str:
    """One token without spaces, in English words."""
    # constants: MAX_VALUE -> max value (also in Integer.MAX_VALUE)
    out = re.sub(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", lambda m: m.group(0).lower(), token)
    for sym, say in SYMBOLS:
        out = out.replace(sym, say)
    words = []
    for w in out.split():
        words.append(" ".join(split_name(p) for p in re.split(r"(?<=\D)(?=\d)|(?<=\d)(?=\D)", w) if p))
    return " ".join(" ".join(words).split())


def runs(text: str, lang: str, native: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """The text as (words, language) pieces, neighbours of the same language merged.
    native: code words said as words of the narration's language, respelled (Integer: Intidscher)."""
    pieces: list[tuple[str, str]] = []
    native = native or {}

    def add(words: str, language: str):
        words = words.strip()
        if not words:
            return
        if not re.search(r"\w", words):
            # punctuation after a code span belongs to the piece before it (never spoken alone)
            if pieces:
                pieces[-1] = (pieces[-1][0] + words, pieces[-1][1])
            return
        if pieces and pieces[-1][1] == language:
            sep = "" if words[0] in ",.;:!?)" else " "
            pieces[-1] = (pieces[-1][0] + sep + words, language)
        else:
            pieces.append((words, language))

    ops = OPERATORS.get(lang, OPERATORS["en"])
    pos = 0
    for m in CODE.finditer(text):
        add(text[pos:m.start()], lang)
        for tok in m.group(1).split():
            if tok in ops:
                add(ops[tok], lang)
            elif NUMBER.match(tok):
                add(tok.rstrip("fFdDlL"), lang)
            elif re.fullmatch(r"\(?[A-Za-z]\)?[,.;:]?", tok):
                add(tok.strip("()"), lang)  # a one-letter name is said as a letter of the narration's language
            else:
                for word in token_words(tok).split():
                    if word in native:
                        add(native[word], lang)
                    else:
                        add(word, "en")
        pos = m.end()
    add(text[pos:], lang)
    return pieces


def plain(text: str) -> str:
    """For subtitles and word counts: the code as written, without backticks."""
    return CODE.sub(lambda m: m.group(1), text)


def spans(text: str) -> list[str]:
    return [t for m in CODE.finditer(text) for t in m.group(1).split()]
