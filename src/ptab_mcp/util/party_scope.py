"""Role-scoped party-name matching for trials/proceedings/search.

WHY THIS EXISTS
---------------
The trials endpoint's ``filters`` mechanism is **not role-scoped for party
names**. A filter naming the petitioner field matches a record whose PATENT
OWNER carries the name just as readily as one whose PETITIONER does, and a
filter naming the patent-owner field returns the identical set. Verified live
2026-08-30 on ``regularPetitionerData.realPartyInInterestName = "WIZ"``: 17
records came back, and five of them (IPR2025-01083 through -01087) have
"Orca Security Ltd." as the petitioner with Wiz as the patent owner. Asking
the same question against ``patentOwnerData.realPartyInInterestName`` returned
the same 17. So "trials X filed" silently became "trials mentioning X" — the
other side's cases, indistinguishable from the party's own.

The **same endpoint's ``q`` parameter does scope by field.** Asked as
``q='regularPetitionerData.realPartyInInterestName:("WIZ")'`` the answer is the
12 proceedings Wiz actually petitioned (live 2026-08-30), with the five
Orca-petitioner rows gone. The divergence is not a small-sample artefact: on
the same day ``Apple AND Inc.`` as petitioner returned 1029 records through
``q`` against 1055 through ``filters`` — 26 proceedings in which Apple is the
patent owner, not the petitioner.

So the fix is a query-language change, not a client-side post-filter: ``q``
carries the role scope, ``filters`` carries everything else, and the API
intersects them (verified live 2026-08-30 alongside ``trialNumber``,
``trialMetaData.trialTypeCode`` and a ``rangeFilters`` window). Totals,
paging and the 404-as-empty envelope all keep working, which a post-filter
over one page could not have preserved.

THE PATENT-OWNER FIELD
----------------------
``patentOwnerData.patentOwnerName`` is unpopulated in the live payload — a
trial record's patent-owner bag carries ``realPartyInInterestName`` and no
``patentOwnerName`` at all (verified live 2026-08-30 on IPR2025-01083, and a
filter or ``q`` clause on the dead field returns HTTP 404 "no matching
records" for a name the corpus certainly holds). Patent-owner clauses
therefore OR the populated field with the dead one, so the search keeps
working unchanged if USPTO ever populates it.

INJECTION SAFETY
----------------
Every token is emitted inside a double-quoted phrase. ``validate_party_name``
already restricts party input to alphanumerics, spaces and ``. - & , ' ( )``,
so a caller cannot reach a quote, a backslash or a bare Lucene operator; the
scrub below is belt-and-braces for any future caller that skips validation.
"""

from typing import Iterable, List, Optional, Sequence, Tuple

#: Characters that would end a quoted phrase or escape out of it. Party-name
#: validation already rejects both; dropped here so no caller can reintroduce
#: them by bypassing it.
_UNSAFE = '"\\'

#: Bare Lucene operators, dropped so an AND-joined value ("WIZ AND Inc.") is
#: rebuilt as explicit clause structure rather than smuggled through as text.
_OPERATORS = ("AND", "OR", "NOT")


def _tokens(value: str) -> List[str]:
    """Split an AND-joined party value back into its literal tokens."""
    out = []
    for token in str(value).split():
        if token.upper() in _OPERATORS:
            continue
        cleaned = "".join(ch for ch in token if ch not in _UNSAFE).strip()
        if cleaned:
            out.append(cleaned)
    return out


def field_clause(fields: Sequence[str], value: str) -> Optional[str]:
    """One role-scoped clause: every token ANDed, across OR-ed field aliases.

    ``field_clause(["a.b"], "Apple AND Inc.")`` -> ``a.b:("Apple" AND "Inc.")``

    Several fields OR together into one parenthesised clause, which is how a
    populated field is paired with a fallback that may populate later.
    Returns None when nothing usable survives the scrub.
    """
    tokens = _tokens(value)
    if not tokens or not fields:
        return None
    phrase = " AND ".join(f'"{t}"' for t in tokens)
    clauses = [f"{f}:({phrase})" for f in fields]
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " OR ".join(clauses) + ")"


def build_party_scope_query(
    clauses: Iterable[Tuple[Sequence[str], Optional[str]]],
) -> Optional[str]:
    """Assemble the ``q`` string for a set of (fields, value) party clauses.

    Clauses with no value are skipped; the survivors are ANDed. Returns None
    when no clause survives, which is the signal to send no ``q`` at all.
    """
    parts = [
        clause
        for fields, value in clauses
        if value
        for clause in [field_clause(fields, value)]
        if clause
    ]
    if not parts:
        return None
    return " AND ".join(parts)


def strip_scoped_filters(
    filters: Sequence[dict], scoped_fields: Iterable[str]
) -> List[dict]:
    """Drop the filter entries whose work the ``q`` clause has taken over.

    The dropped entries stay in ``query_info.filters`` — the response ledger
    still reports which field the caller's ``petitioner_name`` resolved to —
    but sending them upstream alongside the scoped ``q`` would re-admit the
    unscoped match they exist to defeat.
    """
    names = set(scoped_fields)
    return [f for f in filters if f.get("name") not in names]
