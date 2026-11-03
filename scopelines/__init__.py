"""Scopelines: a visualizable semantic representation of LTL.

    from scopelines import find_scopeline
    result = find_scopeline("G(a -> F b)", timeout=60)
    print(result)          # (forall (a) after (sometimes (b)))
"""

from .scopeline import Scopeline, Quantifier
from .search import ScopelineBuilder
from .runner import find_scopeline, Result
from .utils import result_str, result_ltl
