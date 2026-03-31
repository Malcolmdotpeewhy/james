"""
JAMES Unit Tests — Bootstrap
"""

import tempfile

from james.bootstrap import seed_skills, _SEED_SKILLS
from james.skills.skill import SkillStore, Skill


class TestBootstrap:
    def test_seed_skills_empty_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)

            assert store.count == 0

            seeded_count = seed_skills(store)

            assert seeded_count == len(_SEED_SKILLS)
            assert store.count == len(_SEED_SKILLS)

            # Verify all skills are in the store
            for expected_skill in _SEED_SKILLS:
                assert store.get(expected_skill.id) is not None

    def test_seed_skills_existing_skills(self):
        with tempfile.TemporaryDirectory() as td:
            store = SkillStore(td)

            assert store.count == 0
            assert len(_SEED_SKILLS) >= 2

            # Pre-populate store with the first skill
            existing_skill = _SEED_SKILLS[0]
            store.create(existing_skill)

            assert store.count == 1

            seeded_count = seed_skills(store)

            assert seeded_count == len(_SEED_SKILLS) - 1
            assert store.count == len(_SEED_SKILLS)

            # Verify all skills are in the store
            for expected_skill in _SEED_SKILLS:
                assert store.get(expected_skill.id) is not None
