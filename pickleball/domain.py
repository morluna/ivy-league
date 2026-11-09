"""Pure scheduling: no I/O, clocks, or global randomness."""
import random
from collections import Counter
from itertools import combinations


def players_per_court(play_format):
    if play_format not in ('singles', 'doubles'):
        raise ValueError('Choose singles or doubles.')
    return 2 if play_format == 'singles' else 4


def validate(courts, duration, length, play_format='doubles'):
    players_per_court(play_format)
    if type(courts) is not int or type(duration) is not int or (length is not None and type(length) is not int):
        raise ValueError('Court count and minutes must be whole numbers.')
    if not 1 <= courts <= 16 or not 1 <= duration <= 480:
        raise ValueError('Use 1–16 courts and 1–480 total minutes.')
    if length is not None:
        if not 1 <= length <= duration:
            raise ValueError('Round minutes must be positive and no longer than the session; leave blank for manual rounds.')
        if duration // length > 96:
            raise ValueError('A session can contain at most 96 rounds.')


def schedule(players, courts, rounds, seed, history=(), play_format='doubles'):
    """Greedy seeded rotations. Prioritize playing-time balance, then repeated pairs.

    Extra courts remain empty when the roster cannot fill them. No partial matches.
    History includes completed/current rounds, which are never rewritten.
    """
    match_size = players_per_court(play_format)
    if len(players) != len(set(players)):
        raise ValueError('Player IDs must be unique.')
    if courts < 1 or rounds < 0:
        raise ValueError('Invalid court count or round count.')
    rng = random.Random(str(seed))
    games, partners, opponents = Counter(), Counter(), Counter()
    def pair(a, b):
        return tuple(sorted((a, b)))
    def record(r):
        for match in r['matches']:
            a, b = match['teams']
            games.update(a + b)
            if len(a) == len(b) == 2:
                partners.update([pair(*a), pair(*b)])
            opponents.update(pair(x, y) for x in a for y in b)
    for r in history:
        record(r)
    output = []
    slots = min(courts, len(players) // match_size) * match_size
    for _ in range(rounds):
        # Random tie-breaking is local and reproducible.
        order = list(players)
        rng.shuffle(order)
        selected = sorted(order, key=lambda p: games[p])[:slots]
        remaining = selected[:]
        matches = []
        while remaining:
            first = remaining[0]
            if match_size == 2:
                mate = min(remaining[1:], key=lambda p: opponents[pair(first, p)])
                a, b = [first], [mate]
            else:
                # Bound optimization work for large rosters, retaining seeded diversity.
                candidates = list(combinations(remaining[1:], 3))
                if len(candidates) > 600:
                    candidates = rng.sample(candidates, 600)
                best = None
                for triple in candidates:
                    for mate in triple:
                        other = [x for x in triple if x != mate]
                        a, b = [first, mate], other
                        cost = 5 * (partners[pair(*a)] + partners[pair(*b)]) + sum(opponents[pair(x, y)] for x in a for y in b)
                        if best is None or cost < best[0]:
                            best = (cost, a, b)
                _, a, b = best
            matches.append({'court': len(matches) + 1, 'teams': [a, b]})
            remaining = [p for p in remaining if p not in a + b]
        r = {'matches': matches, 'resting': [p for p in players if p not in selected]}
        record(r)
        output.append(r)
    return output
