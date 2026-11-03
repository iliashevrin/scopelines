"""The search for scopelines equivalent to an LTL formula (Algorithm 2 of the
paper), with the syntactic decomposition heuristic of Section V."""

from collections import deque
import spot
spot.setup()
from .utils import *
from .scopeline import Scopeline, Quantifier
import atexit
import buddy


# Exact equivalence keys for events (Boolean combinations of APs under X):
# X is pushed down to the APs, each X^n p becomes a fresh variable, and the
# result's BDD is canonical, so two events are equivalent iff their keys are
# equal. This replaces pairwise spot.are_equivalent() calls in add_events,
# which dominated the search time. One BDD dictionary per process, released
# at exit (spot aborts if registered variables outlive it).
_BDD_DICT = spot.make_bdd_dict()
atexit.register(lambda: _BDD_DICT.unregister_all_my_variables(None))
_EVENT_OPS = (spot.op_Not, spot.op_And, spot.op_Or, spot.op_Implies, spot.op_Equiv, spot.op_Xor)

def _push_x(f, depth=0):
	if f.kind() in (spot.op_tt, spot.op_ff):
		return f
	if f._is(spot.op_ap):
		return f if depth == 0 else spot.formula.ap("__X{}__{}".format(depth, f.ap_name()))
	if f._is(spot.op_X):
		return _push_x(f[0], depth + 1)
	if any(f._is(op) for op in _EVENT_OPS):
		return f.map(lambda c: _push_x(c, depth))
	raise ValueError("not an event: {}".format(f))

def event_key(f):
	return spot.formula_to_bdd(_push_x(f), _BDD_DICT, None)


# Distributive normalization, applied before decomposition: standard LTL
# identities that expose Boolean structure at the top level --
#   G(p & q) = Gp & Gq     over the irredundant CNF of G's body,
#   F(p | q) = Fp | Fq     over the irredundant DNF of F's body,
#   G(Fp | Fq) = GFp | GFq,  F(Gp & Gq) = FGp & FGq,
#   X distributes over the Boolean connectives.
# The normal forms are computed over the body's components (its maximal
# temporal or propositional subformulas) from a BDD (Minato's ISOP), and a
# body whose normal form has more than _MAX_CLAUSES clauses (terms) is left
# alone, which only limits decomposition, never its soundness.
_MAX_CLAUSES = 8

def _propositional(f):
	return f.is_boolean()

# Throughout, is_event tells which subformulas the search can use as one
# event (ScopelineBuilder.is_event): propositional ones, and under
# next_in_events also those with X, so then "a -> X b" is an atom
# rather than a Boolean combination to distribute over.
def _components(f, is_event=_propositional):
	out = []
	def walk(g):
		if any(g._is(op) for op in _EVENT_OPS) and not is_event(g):
			for c in g:
				walk(c)
		elif g not in out:
			out.append(g)
	walk(f)
	return out

def _normal_form(body, cnf, is_event=_propositional):
	components = _components(body, is_event)
	names = {c: spot.formula.ap("__n{}".format(i)) for i, c in enumerate(components)}
	back = {v.ap_name(): c for c, v in names.items()}
	def placeholders(g):
		return names[g] if g in names else g.map(placeholders)
	def restore(g):
		return back[g.ap_name()] if g._is(spot.op_ap) and g.ap_name() in back else g.map(restore)
	b = spot.formula_to_bdd(placeholders(body), _BDD_DICT, None)
	isop = spot.bdd_to_formula(-b if cnf else b, _BDD_DICT)
	if isop.kind() in (spot.op_tt, spot.op_ff):
		return None
	terms = list(isop) if isop._is(spot.op_Or) else [isop]
	if len(terms) > _MAX_CLAUSES:
		return None
	parts = []
	for term in terms:
		literals = [restore(l) for l in (list(term) if term._is(spot.op_And) else [term])]
		# a CNF clause is the negation of a term of the negated body's DNF
		parts.append(spot.formula.Or([spot.formula.Not(l) for l in literals]) if cnf else spot.formula.And(literals))
	return parts

def normalize(f, is_event=_propositional):
	rec = lambda g: normalize(g, is_event)
	if is_event(f):
		return f
	if any(f._is(op) for op in _EVENT_OPS):
		return f.map(rec)
	if f._is(spot.op_X):
		g = f[0]
		if any(g._is(op) for op in _EVENT_OPS) and not g.is_boolean():
			return rec(g.map(spot.formula.X))
		return spot.formula.X(rec(g))
	if f._is(spot.op_G) or f._is(spot.op_F):
		is_g = f._is(spot.op_G)
		wrap = spot.formula.G if is_g else spot.formula.F
		body = rec(f[0])
		if any(body._is(op) for op in _EVENT_OPS) and not is_event(body):
			parts = _normal_form(body, cnf=is_g, is_event=is_event)
			if parts is not None and len(parts) >= 2:
				join = spot.formula.And if is_g else spot.formula.Or
				return join([rec(wrap(p)) for p in parts])
			inner, outer = (spot.op_F, spot.op_Or) if is_g else (spot.op_G, spot.op_And)
			if body._is(outer) and all(c._is(inner) for c in body):
				join = spot.formula.Or if is_g else spot.formula.And
				return join([wrap(c) for c in body])
		return wrap(body)
	return f


def boolean_skeleton(formula, is_event=_propositional):
	# A formula whose top level, after normalize(), is a Boolean
	# combination of two or more components (maximal subformulas that are
	# temporal or events) is returned as (skeleton, components): the
	# skeleton is in negation normal form over And/Or, with literals
	# __c<i> standing for the components. None for any other formula.
	f = normalize(spot.formula(formula), is_event)
	components = []
	def walk(g):
		if any(g._is(op) for op in _EVENT_OPS) and not is_event(g):
			for c in g:
				walk(c)
		elif g not in components:
			components.append(g)
	walk(f)
	if len(components) < 2:
		return None
	names = {c: spot.formula.ap("__c{}".format(i)) for i, c in enumerate(components)}
	def placeholders(g):
		return names[g] if g in names else g.map(placeholders)
	def expand(g):
		if g._is(spot.op_Implies):
			return spot.formula.Or([spot.formula.Not(expand(g[0])), expand(g[1])])
		if g._is(spot.op_Equiv) or g._is(spot.op_Xor):
			a, b = expand(g[0]), expand(g[1])
			if g._is(spot.op_Xor):
				b = spot.formula.Not(b)
			return spot.formula.Or([spot.formula.And([a, b]), spot.formula.And([spot.formula.Not(a), spot.formula.Not(b)])])
		return g.map(expand)
	skeleton = spot.negative_normal_form(expand(spot.simplify(expand(placeholders(f)))))
	def valid(g):
		if g._is(spot.op_ap) or (g._is(spot.op_Not) and g[0]._is(spot.op_ap)):
			return True
		return (g._is(spot.op_And) or g._is(spot.op_Or)) and all(valid(c) for c in g)
	return (skeleton, components) if valid(skeleton) else None


def _component_target(literal, components):
	if literal._is(spot.op_Not):
		return spot.formula.Not(components[int(literal[0].ap_name()[3:])])
	return components[int(literal.ap_name()[3:])]


def _assemble(skeleton, components, found):
	# Joins the components' results along the skeleton into a single
	# result (scopelines, spec), flattening nested and-in-and/or-in-or.
	def build(g):
		if g._is(spot.op_And) or g._is(spot.op_Or):
			op = "and" if g._is(spot.op_And) else "or"
			children = []
			for c in (build(c) for c in g):
				if c[0] == op:
					children.extend(c[1])
				else:
					children.append(c)
			return (op, children)
		scopelines, operator = found[str(_component_target(g, components))]
		if operator in ("and", "or"):
			return (operator, [("leaf", t.copy()) for t in scopelines])
		return ("leaf", scopelines[0].copy())
	leaves = []
	def index(node):
		if node[0] == "leaf":
			leaves.append(node[1])
			return len(leaves) - 1
		return (node[0], tuple(index(c) for c in node[1]))
	root = build(skeleton)
	spec = index(root) if root[0] != "leaf" else ("and", (index(root),))
	return [tuple(leaves), spec]


_DONE = object()

# see ScopelineBuilder.max_size
_SIZE_SLACK = 3


# ScopelineBuilder's refinement search flips a leaf's polarity while keeping
# its strong/weak-ness fixed (see refine()/add_to_list() below) -- i.e. the
# universal axis alone, not a full negate(): forall<->weak_exists,
# strong_forall<->exists.
_FLIP_POLARITY = {
	Quantifier.FORALL: Quantifier.WEAK_EXISTS,
	Quantifier.WEAK_EXISTS: Quantifier.FORALL,
	Quantifier.STRONG_FORALL: Quantifier.EXISTS,
	Quantifier.EXISTS: Quantifier.STRONG_FORALL,
}


class Cover:
	def __init__(self, pos, neg):
		self.pos = pos
		self.neg = neg

	def exact(self):
		return self.pos == True and self.neg == False

	def __str__(self):
		return "pos={}, neg={}".format(self.pos, self.neg)



class ScopelineBuilder:

	def __init__(self, formula, next_in_events=None, max_shapes=None, decompose=True, nested_x=None):

		self.formula = formula
		self.pos_aut = spot.translate(formula, 'Buchi', 'sbacc', 'state-based', 'complete')
		self.neg_aut = spot.translate("!(" + formula + ")", 'Buchi', 'sbacc', 'state-based', 'complete')
		self.events = list(self.pos_aut.ap())
		# scopelines are capped at (number of atomic propositions + 3) nodes
		self.max_size = len(self.events) + _SIZE_SLACK
		# Events contain X exactly when the formula does (None); a component
		# searched for a decomposed formula is told its formula's setting.
		if next_in_events is None:
			def has_x(g):
				return g._is(spot.op_X) or any(has_x(c) for c in g)
			next_in_events = has_x(spot.formula(formula))
		self.next_in_events = next_in_events
		self.decompose = decompose

		# How many results iter_scopelines() yields at most; None means
		# until the search space is exhausted.
		self.max_shapes = max_shapes

		# Additional events
		self.sometimes_events = {}
		self.always_events = {}
		self.parents = {}



		# Heuristic for a good event order
		def switch_u(f):
			if f._is(spot.op_U):
				return u(switch_u(f[1]), switch_u(f[0]))
			else:
				return f.map(switch_u)

		switched = switch_u(spot.formula(formula))


		def appearing(v):
			return str(switched).index(str(v))

		self.events.sort(key = appearing)

		# Boolean connectives whose subtree, if every child is itself one of
		# these (bottoming out at atomic props), is eligible to become a
		# single compound event below -- not just And/Or/Not: Implies/Equiv/
		# Xor are just as purely propositional, e.g. "b -> !c" in
		# "G a && G(b -> !c)" needs to be recognized as one, or no leaf/event
		# can ever represent "G(b -> !c)" at all.
		_BOOLEAN_OPS = (spot.op_And, spot.op_Or, spot.op_Not, spot.op_Implies, spot.op_Equiv, spot.op_Xor)

		# With next_in_events, "X p" over an atomic proposition is another
		# base case, so e.g. "a <-> X b" in "G (a <-> X b)" becomes one
		# compound event, matched by a single leaf.
		#
		# A formula that itself nests X (e.g. "G(a -> XXX b)") widens this
		# to X^k over a literal, k >= 1, so "a -> XXX b" or
		# "a -> (X!a | XX!a)" also becomes one compound event; k never
		# exceeds the formula's own nesting, as events are its subformulas.
		def x_depth(f):
			return max([x_depth(c) for c in f] or [0]) + (1 if f._is(spot.op_X) else 0)
		# a component searched for a decomposed formula (see iter_scopelines)
		# inherits that formula's mode
		if nested_x is None:
			nested_x = x_depth(spot.formula(formula)) >= 2
		nested_x = self.next_in_events and nested_x
		self.nested_x = nested_x

		def _is_next_atomic(f):
			if not (self.next_in_events and f._is(spot.op_X)):
				return False
			if not nested_x:
				return len(f) == 1 and f[0]._is(spot.op_ap)
			while f._is(spot.op_X):
				f = f[0]
			return f._is(spot.op_ap) or (f._is(spot.op_Not) and f[0]._is(spot.op_ap))

		# A node that is itself NOT a single composite event -- either a
		# temporal node, or a boolean connective with at least one
		# non-eligible child (e.g. "!(a & b) -> Fc": the Implies as a whole
		# can't collapse to one event, since Fc has a temporal operator in
		# it) -- still has children worth registering individually: any
		# child that IS itself composite-eligible is a self-contained
		# boolean expression usable as its own node event, whether or not
		# its sibling spoiled the parent's own eligibility. Checking this
		# at every node (not just a temporal node's direct children) is
		# what lets "!(a & b)" in "G(!(a & b) -> Fc)" register as one
		# event instead of being silently dropped -- it sits under an
		# Implies, not directly under G, so the old version (registration
		# only in the non-boolean branch) never reached it.
		lst = list()
		def composite_events(f):
			if f._is(spot.op_ap) or _is_next_atomic(f):
				return True
			is_boolean_node = any(f._is(op) for op in _BOOLEAN_OPS)
			children_eligible = [composite_events(sub) for sub in f]
			if is_boolean_node and all(children_eligible):
				return True
			for sub, eligible in zip(f, children_eligible):
				if eligible and \
					sub not in self.events and sub not in lst and \
					_not(sub) not in self.events and _not(sub) not in lst:
					lst.append(sub)
			return False


		composite_events(spot.formula(formula))

		lst.sort(key = appearing)
		self.events.extend(lst)

		# Residual events: an And/Or that mixes temporal and propositional
		# operands (implications rewritten as disjunctions, so they flatten
		# into it) contributes the And/Or of its propositional operands as
		# one more event, e.g. "q & !r" from "q & !r & F r", or the whole
		# propositional disjunction in "G(phi_1 | ... | phi_n | F r)",
		# which composite_events only registers operand by operand.
		self._is_next_atomic = _is_next_atomic
		eligible = self.is_event

		def no_implies(f):
			if f._is(spot.op_Implies):
				return spot.formula.Or([_not(no_implies(f[0])), no_implies(f[1])])
			return f.map(no_implies)

		known = {event_key(e).id(): e for e in self.events}
		residuals = []
		def collect_residuals(f):
			if (f._is(spot.op_And) or f._is(spot.op_Or)) and not eligible(f):
				operands = [c for c in f if eligible(c)]
				if len(operands) >= 2:
					residual = (spot.formula.And if f._is(spot.op_And) else spot.formula.Or)(operands)
					keys = (event_key(residual).id(), event_key(_not(residual)).id())
					if not any(k in known for k in keys):
						known[keys[0]] = residual
						residuals.append(residual)
			for c in f:
				collect_residuals(c)

		collect_residuals(no_implies(spot.formula(formula)))
		self.events[:0] = residuals
		self._event_keys = {}

		# next_in_events also adds an X-shifted copy of every X-free event,
		# simple or composite (a & b gives a, Xa, b, Xb, a & b, X(a & b)),
		# so an event never nests X. Without the flag, no event contains X.
		if self.next_in_events:
			def has_x(g):
				return g._is(spot.op_X) or any(has_x(c) for c in g)
			shifted = [x(e) for e in self.events if not has_x(e)]
			self.events.extend(e for e in shifted if e not in self.events)

	def is_event(self, f):
		# whether f can be a single event: a Boolean combination of atomic
		# propositions, and under next_in_events of X-atoms (_is_next_atomic)
		if f.kind() in (spot.op_tt, spot.op_ff) or f._is(spot.op_ap) or self._is_next_atomic(f):
			return True
		return any(f._is(op) for op in _EVENT_OPS) and all(self.is_event(c) for c in f)


	def check(self, test):

		neg_test = _not(test)
		pos = None
		neg = None

		# all positive traces have
		if spot.contains(test, self.pos_aut):
			pos = True
		# no positive traces have
		elif spot.contains(neg_test, self.pos_aut):
			pos = False

		# all negative traces have
		if spot.contains(test, self.neg_aut):
			neg = True
		# no negative traces have
		elif spot.contains(neg_test, self.neg_aut):
			neg = False

		return Cover(pos, neg)

	def new_leaves(self, event):
		leaves = [
			Scopeline(event, Quantifier.EXISTS),
			Scopeline(_not(event), Quantifier.EXISTS),
			Scopeline(event, Quantifier.FORALL),
			Scopeline(_not(event), Quantifier.FORALL),
		]

		return leaves


	def refine(self, scopeline, node):

		# node is the chain's leaf (see Scopeline.get_empty_nodes): it gains
		# either a before- or an after-child, never both

		lst = []

		def add_to_list(new_leaf, strictly, direction, switch_universality):

			# This is the scopeline copy we will be adding to the list
			refinement = scopeline.copy()
			node_in_refinement = refinement.find_node(node)

			# This is the leaf copy we will be adding to the scopeline copy
			new_leaf_copy = new_leaf.copy()
			new_leaf_copy.strictly = strictly

			if switch_universality:
				node_in_refinement.quantifier = _FLIP_POLARITY[node_in_refinement.quantifier]

			if node.is_forall() and node.is_leaf():
				node_in_refinement.event = _not(node_in_refinement.event)

			setattr(node_in_refinement, direction, new_leaf_copy)

			lst.append(refinement)

		def leaf_refinements(new_leaf, strictly):

			add_to_list(new_leaf, strictly, "after", switch_universality=False)
			add_to_list(new_leaf, strictly, "before", switch_universality=False)
			add_to_list(new_leaf, strictly, "after", switch_universality=True)
			add_to_list(new_leaf, strictly, "before", switch_universality=True)


		for event in self.events:
			for new_leaf in self.new_leaves(event):
				if event != node.event and event != _not(node.event).simplify():
					leaf_refinements(new_leaf, strictly=False)
				leaf_refinements(new_leaf, strictly=True)


		return lst



	def add_events(self, node, queue, scopeline, events_map, func):

		parent = self.parents[scopeline]

		if parent not in events_map:
			events_map[parent] = set()

		# BDD keys of events_map[parent], kept in sync with it below (the
		# BDDs themselves are kept so their ids stay unique)
		keys, keyed = self._event_keys.setdefault((id(events_map), parent), ({}, set()))
		for e in events_map[parent]:
			if e not in keyed:
				b = event_key(e)
				keys[b.id()] = b
				keyed.add(e)
		constants = (buddy.bddtrue.id(), buddy.bddfalse.id())

		new_events = set()
		new_keys = {}

		for event in events_map[parent]:

			new_event = func(event, node.event).simplify()

			# Filter our redundant new events

			if new_event in new_events:
				continue

			b = event_key(new_event)
			if b.id() in keys or b.id() in constants:
				continue

			refinement = scopeline.copy()
			node_in_refinement = refinement.find_node(node)
			node_in_refinement.event = new_event
			queue.appendleft(refinement)

			self.parents[refinement] = parent
			new_events.add(new_event)
			new_keys[b.id()] = b

		events_map[parent].add(node.event)
		events_map[parent].update(new_events)
		b = event_key(node.event)
		keys[b.id()] = b
		keys.update(new_keys)
		keyed.add(node.event)
		keyed.update(new_events)


	def iter_scopelines(self):

		# Algorithm 2: yields each exact scopeline (or AND/OR combination,
		# see below) as soon as it is found, as [scopelines, operator] (see
		# utils.result_str), up to self.max_shapes results.
		#
		# A formula whose top level is a Boolean combination of components
		# (see boolean_skeleton) is also decomposed: each literal of its
		# skeleton (a component or its negation) gets its own search with
		# the same flags, interleaved node by node with the search for the
		# whole formula, and once every literal has a result, they are
		# joined along the skeleton. The interleaving is deterministic.

		parts = boolean_skeleton(self.formula, self.is_event) if self.decompose else None
		if parts is None:
			yield from self._search(limit=self.max_shapes)
			return

		skeleton, components = parts
		targets = {}
		def collect(g):
			if g._is(spot.op_And) or g._is(spot.op_Or):
				for c in g:
					collect(c)
			else:
				target = _component_target(g, components)
				targets[str(target)] = target
		collect(skeleton)

		searches = [("whole", self._search(heartbeat=True))]
		for name, target in targets.items():
			sub = ScopelineBuilder(str(target), next_in_events=self.next_in_events,
				max_shapes=1, decompose=False, nested_x=self.nested_x)
			searches.append((name, sub._search(heartbeat=True, limit=1)))

		found = {}
		results_count = 0
		while searches:
			for entry in list(searches):
				name, search = entry
				result = next(search, _DONE)
				if result is None:
					continue
				if result is _DONE:
					searches.remove(entry)
					if name != "whole":
						# a literal has no scopeline: no decomposition
						searches = [s for s in searches if s[0] == "whole"]
						break
					continue
				if name == "whole":
					results_count += 1
					yield result
				else:
					found[name] = tuple(result)
					searches.remove(entry)
					if len(found) == len(targets):
						results_count += 1
						yield _assemble(skeleton, components, found)
				if self.max_shapes is not None and results_count >= self.max_shapes:
					return


	def _search(self, heartbeat=False, limit=None):

		# The breadth-first search itself. With heartbeat, it also yields
		# None after every node, so that iter_scopelines can interleave it.

		queue = deque()
		results_count = 0

		for event in self.events:
			for leaf in self.new_leaves(event):
				queue.append(leaf)

		for leaf in queue:
			self.parents[leaf] = None


		while len(queue) > 0:

			scopeline = queue.popleft()
			if heartbeat:
				yield None

			if scopeline.size() == self.max_size:
				continue

			if not scopeline.is_supported():
				continue

			cover = self.check(scopeline.to_ltl())

			if cover.exact():
				results_count += 1
				yield [(scopeline,), ""]
				if limit is not None and results_count == limit:
					return
				continue



			for empty in scopeline.get_empty_nodes():

				if (cover.pos == True and empty.is_exists()) or (cover.neg == False and empty.is_forall()):

					if empty.is_leaf():
						if empty.is_forall():
							self.add_events(empty, queue, scopeline, self.always_events, _or)
						else:
							self.add_events(empty, queue, scopeline, self.sometimes_events, _and)

					for refinement in self.refine(scopeline, empty):
						queue.append(refinement)
						self.parents[refinement] = scopeline
