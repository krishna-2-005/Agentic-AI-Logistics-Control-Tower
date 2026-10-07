"""
Uncertainty for proportions.

Every agent score in this project is a proportion -- cases correct out of cases
run -- and until now each has been reported as a bare number. "20 of 20" and
"150 of 150" are both 100%, and they are not the same claim: the first is
consistent with a true rate of 84%, the second is not.

The Wald interval that most people reach for (p ± 1.96·√(p(1-p)/n)) is wrong in
exactly the place these scores live. At p = 1.0 it has zero width, so a perfect
score on three cases reports no uncertainty at all. Wilson's interval does not
collapse at the boundary and is well behaved at small n, which is why it is the
one used here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 1.96 for 95%. Named rather than inlined because it is the only thing that
#: changes if a different confidence level is ever reported.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    """A count out of a total, with the interval that count actually supports."""

    successes: int
    total: int
    lower: float
    upper: float
    z: float = Z_95

    @property
    def point(self) -> float:
        return self.successes / self.total if self.total else 0.0

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def as_dict(self) -> dict:
        return {
            "successes": self.successes,
            "total": self.total,
            "rate": round(self.point, 4),
            "ci_low": round(self.lower, 4),
            "ci_high": round(self.upper, 4),
        }

    def __str__(self) -> str:
        return (
            f"{self.point:.1%} [{self.lower:.1%}–{self.upper:.1%}]"
            f" ({self.successes}/{self.total})"
        )


def wilson(successes: int, total: int, z: float = Z_95) -> Proportion:
    """The Wilson score interval for `successes` out of `total`.

    At successes == total the upper bound is 1.0 and the lower bound is not, which
    is the behaviour that makes a perfect score on 20 cases legible as weaker
    evidence than a perfect score on 150.
    """
    if total <= 0:
        return Proportion(0, 0, 0.0, 0.0, z)
    if successes < 0 or successes > total:
        raise ValueError(f"{successes} successes out of {total} is not a proportion")

    p = successes / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denom
    return Proportion(successes, total, max(0.0, centre - margin), min(1.0, centre + margin), z)


def beats(a: Proportion, b: Proportion) -> bool:
    """Is `a` better than `b` by more than either interval allows for?

    Deliberately conservative: non-overlapping intervals is a stricter test than a
    two-proportion z-test, so this says "yes" less often than significance would.
    For the claim these evaluations make -- one route is better than another -- the
    stricter reading is the one worth reporting.
    """
    return a.lower > b.upper
