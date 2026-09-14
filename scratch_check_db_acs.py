from app.repositories.project_repo import get_story, story_acceptance_criteria
import json

story = get_story("2188b0fe-8673-4d57-a1f7-ad79bf38d0a4")
print("Story:", story)
if story:
    acs = story_acceptance_criteria(story["id"])
    print("Found ACs count:", len(acs))
    for ac in acs:
        print(f"[{ac.get('ac_key')}] -> {repr(ac.get('text'))}")
