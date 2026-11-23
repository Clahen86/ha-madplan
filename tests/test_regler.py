"""Allergi- og undgå-regler: hvad der rammer en ret."""

import pytest

from custom_components.madplan.planlaegger import _indeholder


def test_undgaa_rammer_ikke_paa_sidste_ord() -> None:
    tekst = "svinemørbrad med sennepsfløde madlavningsfløde 15 %"
    assert not _indeholder(tekst, "mexicansk mad")  # GitHub: "mad" ramte "madlavningsfløde"
    assert not _indeholder(tekst, "indisk køkken", True)  # almene ord heller ikke ved allergi
    assert _indeholder("wok med rød peberfrugt", "rød peberfrugt")
    assert _indeholder("wok med gul peberfrugt", "rød peberfrugt", True)  # allergi: også kun det sidste ord
    assert not _indeholder("wok med gul peberfrugt", "rød peberfrugt")  # undgå: hele udtrykket
    assert _indeholder("rødløg", "løg")


@pytest.mark.parametrize(("tekst", "ord_", "ja"), [
    ("hytteost", "ost", True), ("ostesauce", "ost", True), ("revet ost", "ost", True), ("rostbøf", "ost", False),
    ("frost ærter", "ost", False),
    ("hønseæg", "æg", True), ("æggeblomme", "æg", True), ("ægte vanilje", "æg", False),
    ("andebryst", "and", True), ("mandler", "and", False), ("kokosvand", "and", False),
    ("flødeis", "is", True), ("is med jordbær", "is", True), ("jasminris", "is", False), ("issalat", "is", False),
    ("grøn te", "te", True), ("tern af bacon", "te", False), ("kotelette", "te", False),
    ("rødløg", "løg", True), ("løgpulver", "løg", True),
])
def test_korte_ord(tekst: str, ord_: str, ja: bool) -> None:
    assert _indeholder(tekst, ord_) is ja
