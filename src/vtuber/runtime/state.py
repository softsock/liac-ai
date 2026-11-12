"""The sole M0 state operation: replace one context note at an exact revision."""

from dataclasses import replace

from vtuber.contracts.state import CharacterState, NoteProposal


class RevisionConflict(ValueError):
    pass


def reduce_note(state: CharacterState, proposal: NoteProposal) -> CharacterState:
    if proposal.character_id != state.character_id:
        raise ValueError("Proposal belongs to another character")
    if state.revision != proposal.based_on_revision:
        raise RevisionConflict("revision_conflict")
    return replace(state, revision=state.revision + 1, context_note=proposal.note)
