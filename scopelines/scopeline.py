"""The scopeline data structure, its supported subset, and its translation to LTL
(Algorithm 1 of the paper)."""

from enum import Enum
from .utils import *


# simplify() is costly and refine() copies every scopeline it grows, so each
# distinct event is simplified once and the result reused.
_SIMPLIFIED = {}

def _simplified(event):
	if event not in _SIMPLIFIED:
		_SIMPLIFIED[event] = event.simplify()
	return _SIMPLIFIED[event]


class Quantifier(Enum):

	FORALL = "forall"
	STRONG_FORALL = "strong_forall"
	EXISTS = "exists"
	WEAK_EXISTS = "weak_exists"

	@property
	def is_forall(self):
		return self in (Quantifier.FORALL, Quantifier.STRONG_FORALL)

	@property
	def is_exists(self):
		return self in (Quantifier.EXISTS, Quantifier.WEAK_EXISTS)

	def negate(self):
		return {
			Quantifier.FORALL: Quantifier.EXISTS,
			Quantifier.EXISTS: Quantifier.FORALL,
			Quantifier.STRONG_FORALL: Quantifier.WEAK_EXISTS,
			Quantifier.WEAK_EXISTS: Quantifier.STRONG_FORALL,
		}[self]


class Scopeline:

	def __init__(self, event, quantifier):

		# forall "=" always
		# exists "=" sometimes

		# before + not strictly = before, including event
		# after + not strictly = after, including event

		# A scopeline is a chain: every node has at most one child, either
		# a before-child or an after-child, never both.

		self.quantifier = quantifier
		self.event = _simplified(event)
		self.strictly = False
		self.before = None
		self.after = None

	def __eq__(self, other):
		if other is None:
			return False
		return (self.quantifier == other.quantifier and self.event == other.event and
			self.strictly == other.strictly and self.before == other.before and self.after == other.after)


	def __str__(self):

		if self.is_leaf():

			if self.quantifier == Quantifier.FORALL:
				quantifier = "always"
			elif self.quantifier == Quantifier.EXISTS:
				quantifier = "sometimes"

			return f'({quantifier} ({str(self.event)}))'


		quantifier = self.quantifier.value


		if self.before is not None and self.after is None:
			return f'({quantifier} ({str(self.event)}) {"strictly " if self.before.strictly else ""}before {str(self.before)})'

		if self.after is not None and self.before is None:
			return f'({quantifier} ({str(self.event)}) {"strictly " if self.after.strictly else ""}after {str(self.after)})'

		raise ValueError("A scopeline node has at most one child")



	def __hash__(self):
		return hash(str(self))


	def copy(self):
		copy = Scopeline(self.event, self.quantifier)
		copy.strictly = self.strictly
		if self.before is not None:
			copy.before = self.before.copy()
		if self.after is not None:
			copy.after = self.after.copy()
		return copy


	def size(self):

		before_size = self.before.size() if self.before is not None else 0
		after_size = self.after.size() if self.after is not None else 0
		return before_size + after_size + 1


	def depth(self):

		before_depth = self.before.depth() if self.before is not None else 0
		after_depth = self.after.depth() if self.after is not None else 0
		return max(before_depth, after_depth) + 1



	def is_forall(self):
		return self.quantifier.is_forall

	def is_exists(self):
		return self.quantifier.is_exists

	def is_strong_forall(self):
		return self.quantifier == Quantifier.STRONG_FORALL

	def is_weak_exists(self):
		return self.quantifier == Quantifier.WEAK_EXISTS

	def must_appear(self):
		return self.quantifier in (Quantifier.STRONG_FORALL, Quantifier.EXISTS)



	def negate(self):
		self.quantifier = self.quantifier.negate()
		if self.before is not None:
			self.before.negate()
		if self.after is not None:
			self.after.negate()
		if self.is_leaf():
			self.event = _not(self.event)



	def get_empty_nodes(self):

		# The only node a chain can grow at is its last one, the leaf.
		if self.before is not None:
			return self.before.get_empty_nodes()
		if self.after is not None:
			return self.after.get_empty_nodes()
		return [self]



	def find_node(self, node):
		if self == node:
			return self
		else:
			if self.before is not None:
				res = self.before.find_node(node)
				if res:
					return res
			if self.after is not None:
				res = self.after.find_node(node)
				if res:
					return res




	def get_events(self):
		before_events = self.before.get_events() if self.before is not None else []
		after_events = self.after.get_events() if self.after is not None else []
		events = before_events + after_events
		events.insert(0, self.event)
		return events


	def is_leaf(self):
		return self.before is None and self.after is None



	def is_supported(self, bound=None):

		# Entry-point guard: a "before" node's target may only be a chain
		# of "after" hops ending in a leaf, with polarity matching the
		# bound it establishes. Supersedes the single raise at the bottom
		# of _to_ltl() -- that one condition only catches matched universal
		# flags; this walks the whole tree once and also catches nested
		# "before" under an active bound, strong_forall/weak_exists
		# reached under a bound, and a strict "after" hop reached under an
		# inclusive bound, all of which _to_ltl() would otherwise silently
		# compute a wrong answer for instead of flagging.

		if self.before is not None and self.after is not None:
			# scopelines are chains -- a node has a before- or an after-child, not both
			return False

		if bound is not None:

			if self.before is not None:
				# a "before" node may not appear under an existing bound
				return False

			if self.is_forall() == bound.is_forall():
				# polarity must differ from the enclosing bound
				return False

			if self.is_strong_forall() or self.is_weak_exists():
				# strong_forall/weak_exists is not supported under a bound
				return False

			if not bound.before.strictly and self.after is not None and self.after.strictly:
				# a strict "after" hop is not supported under an inclusive bound
				return False

		if self.before is not None and not self.before.is_supported(bound=self):
			return False

		if self.after is not None and not self.after.is_supported(bound=bound):
			return False

		return True


	def to_ltl(self):

		# Public entry point: runs the precondition check once, then
		# delegates to the actual (precondition-assumed) computation.

		if not self.is_supported():
			raise Exception("Unsupported Scopeline")

		return self._to_ltl()


	def _to_ltl(self, bound_ltl=None, strictly_before=None):

		if self.after is None: # Leaf with or without before

			if self.is_forall():

				ltl = g(self.event)

			else: # self.is_exists()

				ltl = f(self.event)

		else: # Recurse directly into the after chain

			ltl = self.after._to_ltl(bound_ltl, strictly_before)
			if self.after.strictly:
				ltl = x(ltl)


			if self.is_forall():

				ltl = g(implies(self.event, ltl))

			else: # self.is_exists()

				ltl = f(_and(self.event, ltl))



		if self.before is not None:

			# self is the new bound: a before-node has no after-child, so
			# ltl is G(event) or F(event) here and the bound is the event itself

			bound_ltl = peel(ltl)

			ltl = self.before._to_ltl(bound_ltl, self.before.strictly)


		# Handle the bound
		elif strictly_before is not None:

			ltl = peel(ltl)

			if self.is_forall():

				if strictly_before:
					ltl = u(ltl, bound_ltl)
				else:
					ltl = u(ltl, _and(ltl, bound_ltl))

			else: # self.is_exists()

				if strictly_before:
					ltl = _or(u(_not(bound_ltl), _and(ltl, _not(bound_ltl))), g(_not(bound_ltl)))
				else:
					ltl = _or(u(_not(bound_ltl), ltl), g(_not(bound_ltl)))


		if self.is_strong_forall():
			ltl = _and(ltl, f(self.event))
		elif self.is_weak_exists():
			ltl = _or(ltl, g(_not(self.event)))

		return ltl
