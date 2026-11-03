"""Running the search for one formula under a hard time budget.

The search runs in a child process: spot's C++ calls cannot be interrupted
from Python, so the time budget is enforced by terminating that process.
The child sends back the printed result, which the parent parses back into
Scopeline objects (see parse.py)."""

import multiprocessing
import time
from dataclasses import dataclass, field

from .parse import parse_result
from .search import ScopelineBuilder
from .utils import result_str

_FORK = multiprocessing.get_context("fork")


@dataclass
class Result:
	status: str                      # "found", "exhausted" (no scopeline in the search space), or "timeout"
	scopelines: list = field(default_factory=list)
	operator: object = ""            # "" for a single scopeline, "and"/"or", or a nested spec (see utils)
	decomposed: bool = False         # whether the result joins the scopelines of the formula's components
	elapsed: float = None            # search time in seconds (None on timeout)

	@property
	def found(self):
		return self.status == "found"

	def __str__(self):
		return result_str(self.scopelines, self.operator) if self.found else "<{}>".format(self.status)


def _search(formula, conn, options):
	start = time.monotonic()
	result = next(iter(ScopelineBuilder(formula, max_shapes=1, **options).iter_scopelines()), None)
	elapsed = time.monotonic() - start
	if result is None:
		conn.send(None)
	else:
		scopelines, operator = result
		conn.send((result_str(scopelines, operator), isinstance(operator, tuple), elapsed))
	conn.close()


def find_scopeline(formula, timeout=60, **options):
	"""Searches for a scopeline equivalent to the LTL formula (a string in
	spot syntax) within `timeout` seconds, and returns a Result. `options`
	are passed to ScopelineBuilder (e.g. decompose=False)."""
	receiver, sender = _FORK.Pipe(duplex=False)
	process = _FORK.Process(target=_search, args=(formula, sender, options))
	process.start()
	sender.close()
	try:
		if not receiver.poll(timeout):
			return Result("timeout")
		message = receiver.recv()
	except EOFError:
		raise RuntimeError("the search process for {!r} died".format(formula))
	finally:
		if process.is_alive():
			process.terminate()
		process.join()
	if message is None:
		return Result("exhausted")
	text, decomposed, elapsed = message
	scopelines, operator = parse_result(text)
	return Result("found", scopelines, operator or "", decomposed, elapsed)
