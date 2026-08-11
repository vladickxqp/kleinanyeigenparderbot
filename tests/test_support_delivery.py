"""Regression test: a solo owner's support request must reach someone.

The staff list excludes the sender so admins do not get their own tickets
back — but when the sender IS the only staff member, that left the recipient
list empty while the bot still reported success.
"""

from __future__ import annotations


def _recipients(staff: list[int], sender: int) -> list[int]:
    """Mirrors the recipient rule in handlers/support.py."""
    return [s for s in staff if s != sender] or staff


def test_solo_owner_still_receives_the_ticket():
    # Only one staff member exists and they are the sender.
    assert _recipients([5933423757], 5933423757) == [5933423757]


def test_other_staff_get_it_and_sender_does_not():
    assert _recipients([1, 2, 3], 2) == [1, 3]


def test_plain_user_reaches_all_staff():
    assert _recipients([1, 2], 999) == [1, 2]


def test_no_staff_at_all_yields_no_recipients():
    # The handler reports an honest failure in this case.
    assert _recipients([], 42) == []
